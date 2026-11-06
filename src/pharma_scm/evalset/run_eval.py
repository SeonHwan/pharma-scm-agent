"""평가셋 전체를 에이전트에 돌려 문항별 결과를 data/runs/<run_id>/<문항id>.json에 저장한다.

이미 결과 파일이 있는 문항은 건너뛴다(중단 후 이어서 실행). 결과를 보고 프롬프트를 바꾸면
PROMPT_VERSION을 올리고 새 run_id로 돌린다 — 기존 결과를 덮어쓰지 않는다.
실행: uv run python -m pharma_scm.evalset.run_eval [--dry-run] [--run-id ID] [--workers N]
"""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .. import config
from ..agent.graph import MAX_TOOL_ROUNDS, build_graph
from ..agent.prompt import PROMPT_SHA, PROMPT_VERSION
from ..agent.run import ask
from .grader import grade
from pathlib import Path
from typing import Any
from ..typedefs import Question

QUESTIONS = config.ROOT / "eval" / "questions.jsonl"
RESULT_CLIP = 2000


def load_questions() -> list[Question]:
    return [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines()]


def run_one(q: Question, graph: Any, out_dir: Path) -> dict[str, Any]:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"main_{PROMPT_VERSION}")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    qs = load_questions()
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
            "questions_md5": hashlib.md5(QUESTIONS.read_bytes()).hexdigest()}, indent=1))
    graph = build_graph()
    done = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(lambda q: run_one(q, graph, out_dir), todo):
            done += 1
            g = r["grade"]
            print(f"[{done}/{len(todo)}] {r['id']} {'PASS' if g['pass'] else 'FAIL'} "
                  f"{g['reason'][:60]} {r['error'] or ''}", flush=True)


if __name__ == "__main__":
    main()
