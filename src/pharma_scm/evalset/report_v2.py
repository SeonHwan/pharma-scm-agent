"""평가셋 v2 결과 집계와 두 실행 비교(docs/eval_v2_protocol.md §5).

    uv run python -m pharma_scm.evalset.report_v2 <run_id>                 # 한 실행 집계
    uv run python -m pharma_scm.evalset.report_v2 <기준 run_id> <개선 run_id> [--split test]   # 짝지은 비교

비교는 두 실행에 모두 있는 문항만 쓴다. 정답률 차이는 McNemar 정확 검정(엇갈린 문항 수에 대한 양측 이항 검정)으로 본다.
"""

import argparse
import json
from math import comb

from .. import config
from .report import fmt
from .run_eval import load_questions

RUNS = config.ROOT / "data" / "runs"


def load_run(run_id):
    d = RUNS / run_id
    if not d.is_dir():
        raise SystemExit(f"실행 결과가 없다: {d}")
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.json") if p.stem != "_meta"}


def tokens(rs):
    t = [r["tokens"] for r in rs]
    return {"llm_calls": sum(x["llm_calls"] for x in t), "input": sum(x["input"] for x in t),
            "output": sum(x["output"] for x in t)}


def summarize(run, qs, split=None):
    rs = [r for i, r in run.items() if i in qs and (split is None or qs[i]["split"] == split)]
    out = {"n": len(rs), "pass": sum(r["grade"]["pass"] for r in rs), "by_type": {},
           "format_bad": sum(not r["grade"]["format_ok"] for r in rs), "errors": sum(bool(r["error"]) for r in rs),
           "tokens": tokens(rs)}
    for t in sorted({qs[r["id"]]["type"] for r in rs}):
        sub = [r for r in rs if qs[r["id"]]["type"] == t]
        out["by_type"][t] = (sum(r["grade"]["pass"] for r in sub), len(sub))
    out["failures"] = sorted((r["id"], r["grade"]["reason"]) for r in rs if not r["grade"]["pass"])
    return out


def mcnemar_exact(b, c):
    """엇갈린 문항: b = 기준만 맞음, c = 개선만 맞음. 양측 p값."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def compare(base, new, qs, split=None):
    ids = sorted(i for i in base.keys() & new.keys() if i in qs and (split is None or qs[i]["split"] == split))
    b = [i for i in ids if base[i]["grade"]["pass"] and not new[i]["grade"]["pass"]]
    c = [i for i in ids if new[i]["grade"]["pass"] and not base[i]["grade"]["pass"]]
    tb, tn = tokens([base[i] for i in ids]), tokens([new[i] for i in ids])
    return {"n": len(ids), "base_pass": sum(base[i]["grade"]["pass"] for i in ids),
            "new_pass": sum(new[i]["grade"]["pass"] for i in ids), "only_base": b, "only_new": c,
            "p_value": mcnemar_exact(len(b), len(c)), "tokens_base": tb, "tokens_new": tn}


def print_summary(run_id, s):
    print(f"run {run_id}: 문항 {s['n']}개, 정답 {fmt(s['pass'], s['n'])}")
    for t, (k, n) in s["by_type"].items():
        print(f"  {t}: {fmt(k, n)}")
    tk = s["tokens"]
    print(f"  형식 위반 {s['format_bad']}건, 실행 오류 {s['errors']}건, LLM 호출 {tk['llm_calls']}회, "
          f"입력 {tk['input']:,} / 출력 {tk['output']:,} 토큰")
    for i, reason in s["failures"]:
        print(f"  실패 {i}: {reason[:90]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="run_id 하나(집계) 또는 둘(기준, 개선 비교)")
    ap.add_argument("--split", choices=["dev", "test"], default=None)
    a = ap.parse_args(argv)
    qs = {q["id"]: q for q in load_questions("v2")}
    if len(a.runs) == 1:
        print_summary(a.runs[0], summarize(load_run(a.runs[0]), qs, a.split))
        return
    base_id, new_id = a.runs[:2]
    base, new = load_run(base_id), load_run(new_id)
    for rid, run in ((base_id, base), (new_id, new)):
        print_summary(rid, summarize(run, qs, a.split))
    c = compare(base, new, qs, a.split)
    diff = (c["new_pass"] - c["base_pass"]) / c["n"] * 100 if c["n"] else 0.0
    tin_b, tin_n = c["tokens_base"]["input"], c["tokens_new"]["input"]
    print(f"\n[짝지은 비교] 공통 {c['n']}문항: 기준 {c['base_pass']} → 개선 {c['new_pass']} ({diff:+.1f}%p), "
          f"기준만 맞음 {len(c['only_base'])}, 개선만 맞음 {len(c['only_new'])}, McNemar 정확 p={c['p_value']:.4f}")
    if tin_b:
        print(f"  입력 토큰 {tin_b:,} → {tin_n:,} ({(tin_n - tin_b) / tin_b * 100:+.1f}%)")
    print(f"  기준만 맞음: {', '.join(c['only_base']) or '없음'}")
    print(f"  개선만 맞음: {', '.join(c['only_new']) or '없음'}")


if __name__ == "__main__":
    main()
