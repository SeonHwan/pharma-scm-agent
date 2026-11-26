"""평가셋 전체를 에이전트에 돌려 문항별 결과를 data/runs/<run_id>/<문항id>.json에 저장한다.

이미 결과 파일이 있는 문항은 건너뛴다(중단 후 이어서 실행). 결과를 보고 프롬프트를 바꾸면
PROMPT_VERSION을 올리고 새 run_id로 돌린다 — 기존 결과를 덮어쓰지 않는다.
실행: uv run python -m pharma_scm.evalset.run_eval [--dry-run] [--run-id ID] [--workers N]
      [--ids A001,B002 ...] [--sha 커밋해시] [--strict] [--set v1|v2] [--split dev|test]
--ids로 일부 문항만, --sha로 run_id에 커밋 해시를 넣어 옛 결과 재사용을 막는다(기본 run_id는 main_<버전>).
--strict는 실행 중 예외로 실패한 문항이 있으면 종료코드 1로 끝낸다(스모크·CI용). 기본은 항상 0.
--set v2는 평가셋 v2(eval/questions_v2.jsonl, docs/eval_v2_protocol.md), --split은 v2의 dev/test 절반만 고른다.
"""

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .. import config
from ..agent.graph import MAX_TOOL_ROUNDS, build_graph
from ..agent.prompt import PROMPT_SHA, PROMPT_VERSION
from ..agent.run import ask
from .grader import grade

QUESTIONS = config.ROOT / "eval" / "questions.jsonl"
QUESTION_SETS = {"v1": QUESTIONS, "v2": config.ROOT / "eval" / "questions_v2.jsonl"}
RESULT_CLIP = 2000


def load_questions(qset="v1"):
    return [json.loads(x) for x in QUESTION_SETS[qset].read_text(encoding="utf-8").splitlines()]


def parse_ids(text):
    """쉼표·공백으로 구분된 문항 ID 목록(파일 내용을 그대로 넘겨도 된다). 중복은 첫 번째만 남긴다."""
    return list(dict.fromkeys(x for x in re.split(r"[,\s]+", text) if x))


def select_questions(qs, ids):
    if ids is None:
        return qs
    known = {q["id"] for q in qs}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"평가셋에 없는 문항 ID: {', '.join(unknown)}")
    want = set(ids)
    return [q for q in qs if q["id"] in want]


def default_run_id(sha, qset="v1"):
    prefix = "main" if qset == "v1" else qset
    return f"{prefix}_{PROMPT_VERSION}_{sha[:8]}" if sha else f"{prefix}_{PROMPT_VERSION}"


def count_problems(results):
    """이번에 실행한 결과에서 (실행 오류 문항 수, 형식 위반 문항 수). 오류 문항은 형식 위반에서 뺀다."""
    errors = sum(1 for r in results if r["error"])
    fmt_bad = sum(1 for r in results if not r["error"] and not r["grade"]["format_ok"])
    return errors, fmt_bad


def run_one(q, graph, out_dir):
    try:
        r = ask(q["question"], graph)
    except Exception as e:  # 한 문항의 실패가 전체 실행을 멈추지 않게 한다
        r = {"question": q["question"], "answer": None, "tool_calls": [], "tools_called": [],
             "tokens": {"input": 0, "output": 0, "llm_calls": 0}, "latency_s": None,
             "error": f"exception:{type(e).__name__}:{str(e)[:200]}",
             "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA}
    for c in r["tool_calls"]:
        c["result"] = (c.get("result") or "")[:RESULT_CLIP]
    r["id"], r["type"] = q["id"], q["type"]
    r["grade"] = grade(q, r["answer"] or "", r["tools_called"])
    (out_dir / f"{q['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None, help="기본: main_<프롬프트 버전>[_<--sha 앞 8자>]")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ids", default=None, help="실행할 문항 ID(쉼표·공백 구분). 없으면 전체")
    ap.add_argument("--sha", default=None, help="run_id에 넣을 커밋 해시")
    ap.add_argument("--strict", action="store_true", help="실행 오류 문항이 있으면 종료코드 1")
    ap.add_argument("--set", dest="qset", choices=sorted(QUESTION_SETS), default="v1", help="평가셋 버전")
    ap.add_argument("--split", choices=["dev", "test"], default=None, help="v2의 dev/test 절반만 실행")
    a = ap.parse_args(argv)
    if a.split and a.qset == "v1":
        ap.error("--split은 --set v2에서만 쓴다")
    a.run_id = a.run_id or default_run_id(a.sha, a.qset)
    try:
        qs = select_questions(load_questions(a.qset), None if a.ids is None else parse_ids(a.ids))
    except ValueError as e:
        ap.error(str(e))
    if a.split:
        qs = [q for q in qs if q["split"] == a.split]
    out_dir = config.ROOT / "data" / "runs" / a.run_id
    todo = [q for q in qs if not (out_dir / f"{q['id']}.json").exists()]
    print(f"run_id={a.run_id} 프롬프트 {PROMPT_VERSION} {PROMPT_SHA} 모델 {config.AGENT_MODEL}")
    print(f"문항 {len(qs)}개 중 실행할 것 {len(todo)}개 (이미 있는 {len(qs) - len(todo)}개는 건너뜀)")
    print(f"예상 LLM 호출 {len(todo) * 2}~{len(todo) * 3}회 (스모크 평균 1.8회/문항), "
          f"상한 {len(todo) * (MAX_TOOL_ROUNDS + 1)}회")
    if a.dry_run:
        print("API 호출은 하지 않았다.")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = out_dir / "_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({
            "run_id": a.run_id, "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA,
            "model": config.AGENT_MODEL, "started": datetime.now().isoformat(timespec="seconds"),
            "question_set": a.qset, "split": a.split,
            "questions_md5": hashlib.md5(QUESTION_SETS[a.qset].read_bytes()).hexdigest()}, indent=1))
    graph = build_graph()
    done = 0
    results = []
    with ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(lambda q: run_one(q, graph, out_dir), todo):
            done += 1
            results.append(r)
            g = r["grade"]
            print(f"[{done}/{len(todo)}] {r['id']} {'PASS' if g['pass'] else 'FAIL'} "
                  f"{g['reason'][:60]} {r['error'] or ''}", flush=True)
    errors, fmt_bad = count_problems(results)
    print(f"이번 실행 {len(results)}개: 실행 오류 {errors}건, 형식 위반 {fmt_bad}건")
    if a.strict and errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
