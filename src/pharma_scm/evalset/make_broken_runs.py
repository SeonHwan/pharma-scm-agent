"""통과한 실제 답의 `최종 답:` 줄을 규칙으로 망가뜨려 채점기가 잡는지 시험. 모델 호출 없음.

기대 결과는 실행 전에 등록. 원본 결과는 건드리지 않고
data/runs_broken/<run_id>/manifest.json에 변형 내역을 기록.
실행: uv run python -m pharma_scm.evalset.make_broken_runs <run_id>
"""

import json
import random
import sys
from collections import defaultdict

from .. import config
from .grader import _FINAL, STATUS_LABELS, grade
from .run_eval import load_questions

SEED = 20261103


def replace_final(text, new_line):
    """마지막 `최종 답:` 줄의 내용을 바꿈. 줄이 없으면 None."""
    if text is None:
        return None
    ms = list(_FINAL.finditer(text))
    if not ms:
        return None
    m = ms[-1]
    return text[:m.start(1)] + new_line + text[m.end(1):]


def drop_final(text):
    if text is None:
        return None
    ms = list(_FINAL.finditer(text))
    if not ms:
        return None
    return (text[:ms[-1].start()] + text[ms[-1].end():]).rstrip()


def _fmt(v):
    return f"{v:,}" if isinstance(v, int) else f"{v:.1f}"


def mutations(q, r, ctx):
    """[(변형 이름, 새 답 텍스트, 새 도구 목록, 기대 통과 여부, 기대 tool_exact)] — 적용 불가면 생략."""
    g, kind, ans, tools = q["gold"], q["gold"]["kind"], r["answer"], r["tools_called"]
    rng, out = ctx["rng"], []

    def add(name, text, expect_pass=False, tools_=None, expect_tool=None):
        if text is not None:
            out.append((name, text, tools if tools_ is None else tools_, expect_pass, expect_tool))

    if kind in ("number", "status_number"):
        v = g["value"] if kind == "number" else g["value"]["number"]
        pre = f"{g['value']['status']}, " if kind == "status_number" else ""
        if isinstance(v, int):
            add("number_off_by_one", replace_final(ans, pre + _fmt(v + 1)))
        else:
            add("number_off_by_tenth", replace_final(ans, pre + _fmt(round(v + 0.1, 1))))
            add("within_tolerance", replace_final(ans, pre + f"{v + 0.04:.2f}"), expect_pass=True)
    if kind in ("status", "status_number"):
        cur = g["value"] if kind == "status" else g["value"]["status"]
        other = next(x for x in STATUS_LABELS if x != cur)
        suffix = "" if kind == "status" else f", {_fmt(g['value']['number'])}"
        add("status_flip", replace_final(ans, other + suffix))
    if kind == "set":
        gold = list(g["value"])
        add("set_drop", replace_final(ans, ", ".join(gold[1:]) or "없음"))
        extra = next(s for s in ctx["all_skus"] if s not in gold)
        add("set_add", replace_final(ans, ", ".join(gold + [extra])))
    if kind == "sections":
        others = [s for s in ctx["all_sections"] if s != g["value"]]
        add("section_wrong", replace_final(ans, rng.choice(others)))
        add("section_too_many", replace_final(ans, ", ".join([g["value"]] + rng.sample(others, 2))))
    if kind == "refusal":
        add("answered_instead", replace_final(ans, "42"))
    else:
        add("over_refuse", replace_final(ans, "거절"))
        pool = [o for o in ctx["by_kind"][kind] if o["id"] != q["id"] and o["gold"] != g]
        if pool:
            o = rng.choice(pool)
            add("wrong_answer", replace_final(ans, _gold_line(o)))
    add("format_drop", drop_final(ans))
    if q["type"] in "ABC" and len(q["expected_tools"]) == 1:
        add("no_tool_call", ans, expect_pass=True, tools_=[], expect_tool=False)
    return out


def _gold_line(q):
    g = q["gold"]
    k = g["kind"]
    if k == "number":
        return _fmt(g["value"])
    if k == "status":
        return g["value"]
    if k == "status_number":
        return f"{g['value']['status']}, {_fmt(g['value']['number'])}"
    if k == "set":
        return ", ".join(g["value"]) or "없음"
    return g["value"]


def main(run_id):
    qs = {q["id"]: q for q in load_questions()}
    run_dir = config.ROOT / "data" / "runs" / run_id
    runs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in run_dir.glob("[A-E]*.json")}
    passed = {i: r for i, r in runs.items() if r["grade"]["pass"]}
    by_kind = defaultdict(list)
    for q in qs.values():
        by_kind[q["gold"]["kind"]].append(q)
    ctx = {"rng": random.Random(SEED), "by_kind": by_kind,
           "all_skus": sorted({f"SKU-{i:03d}" for i in range(1, 91)}),
           "all_sections": sorted(q["gold"]["value"] for q in by_kind["sections"])}
    stats = defaultdict(lambda: [0, 0])
    misses, manifest = [], []
    for i in sorted(passed):
        q, r = qs[i], passed[i]
        for name, text, tools, exp_pass, exp_tool in mutations(q, r, ctx):
            res = grade(q, text, tools)
            ok = res["pass"] == exp_pass and (exp_tool is None or res["tool_exact"] == exp_tool)
            stats[name][0] += 1
            stats[name][1] += ok
            manifest.append({"id": i, "mutation": name, "as_expected": ok, "grade": res})
            if not ok:
                misses.append((i, name, res["pass"], res["reason"]))
    out_dir = config.ROOT / "data" / "runs_broken" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(f"원본 통과 {len(passed)}문항에서 변형 {sum(v[0] for v in stats.values())}건")
    print(f"{'변형':20s} {'건수':>5s} {'기대대로':>8s}")
    for name, (n, k) in sorted(stats.items()):
        print(f"{name:20s} {n:5d} {k:8d}")
    tot_n, tot_k = sum(v[0] for v in stats.values()), sum(v[1] for v in stats.values())
    print(f"합계 {tot_k}/{tot_n} 기대대로")
    fmt_err = sum(1 for m in manifest if m["mutation"] == "format_drop" and not m["grade"]["format_ok"])
    print(f"format_drop 중 형식 오류로 분류됨: {fmt_err}/{stats['format_drop'][0]}")
    for m in misses:
        print("기대와 다름:", m)


if __name__ == "__main__":
    main(sys.argv[1])
