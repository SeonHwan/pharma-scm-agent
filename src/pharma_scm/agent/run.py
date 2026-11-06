"""질문 하나를 에이전트에 넣고 답·도구 호출·토큰·지연을 돌려준다.

실행: uv run python -m pharma_scm.agent.run "질문"  [--dry-run] [--trace]
"""

import argparse
import json
import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from .graph import MAX_TOOL_ROUNDS, RECURSION_LIMIT, build_graph
from .prompt import PROMPT_SHA, PROMPT_VERSION, SYSTEM_PROMPT
from typing import Any
from langchain_core.callbacks import BaseCallbackHandler
from ..typedefs import AskResult


def _text(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def ask(question: str, graph: Any = None,
        callbacks: list[BaseCallbackHandler] | None = None) -> AskResult:
    graph = graph or build_graph()
    t0 = time.perf_counter()
    error = None
    try:
        out = graph.invoke({"messages": [HumanMessage(question)]},
                           {"recursion_limit": RECURSION_LIMIT, "callbacks": callbacks or []})
        msgs = out["messages"]
    except GraphRecursionError:
        msgs, error = [], "loop_limit"
    calls, tokens = [], {"input": 0, "output": 0, "llm_calls": 0}
    results = {}
    for m in msgs:
        if isinstance(m, ToolMessage):
            results[m.tool_call_id] = _text(m.content)
        if isinstance(m, AIMessage):
            tokens["llm_calls"] += 1
            u = m.usage_metadata or {}
            tokens["input"] += u.get("input_tokens", 0)
            tokens["output"] += u.get("output_tokens", 0)
            calls += [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls]
    for c in calls:
        c["result"] = results.get(c["id"])
    final = next((_text(m.content) for m in reversed(msgs) if isinstance(m, AIMessage)
                  and not m.tool_calls), None)
    return {"question": question, "answer": final, "tool_calls": calls,
            "tools_called": [c["name"] for c in calls], "tokens": tokens, "error": error,
            "latency_s": round(time.perf_counter() - t0, 2),
            "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--dry-run", action="store_true", help="API를 부르지 않고 호출 규모만 본다")
    ap.add_argument("--trace", action="store_true", help="도구 호출과 결과를 출력한다")
    a = ap.parse_args()
    if a.dry_run:
        print(f"프롬프트 {PROMPT_VERSION} sha256={PROMPT_SHA}, 시스템 프롬프트 {len(SYSTEM_PROMPT)}자")
        print(f"LLM 호출: 최소 1회, 최대 {MAX_TOOL_ROUNDS + 1}회 (도구 왕복 상한 {MAX_TOOL_ROUNDS})")
        print("API 호출은 하지 않았다.")
        return
    r = ask(a.question)
    if a.trace:
        for c in r["tool_calls"]:
            print(f"[{c['name']}] {json.dumps(c['args'], ensure_ascii=False)}")
            print("   →", (c["result"] or "")[:300])
    print(r["answer"] if r["answer"] else f"(답 없음: {r['error']})")
    print(f"\n도구 {r['tools_called']} | 토큰 {r['tokens']} | {r['latency_s']}s")


if __name__ == "__main__":
    main()
