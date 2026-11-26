"""질문 하나를 에이전트에 넣고 답·도구 호출·토큰·지연을 돌려준다.

실행: uv run python -m pharma_scm.agent.run "질문"  [--dry-run] [--trace]
"""

import argparse
import json
import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from .. import config
from . import tracing
from .graph import MAX_TOOL_ROUNDS, PROMPT_CACHE, RECURSION_LIMIT, build_graph
from .prompt import PROMPT_SHA, PROMPT_VERSION, SYSTEM_PROMPT


def _text(content):
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def ask(question, graph=None, callbacks=None, trace=None):
    """trace = {"name", "external_id", "session_id", "tags", "metadata"} (모두 선택). Langfuse가 켜져 있으면
    트레이스 하나를 만들고 결과의 trace_id에 넣는다(docs/langfuse.md). 꺼져 있으면 trace_id는 None."""
    graph = graph or build_graph()
    trace = trace or {}
    trace_id = None
    callbacks = list(callbacks or [])
    metadata = {}
    if tracing.enabled():
        ext = trace.get("external_id")
        trace_id = tracing.trace_id_for(ext) if ext else None
        lf = tracing.handler(trace_id)
        callbacks.append(lf)
        metadata = tracing.run_metadata(
            trace.get("name", "ask"), session_id=trace.get("session_id"), tags=trace.get("tags"),
            prompt_version=PROMPT_VERSION, prompt_sha=PROMPT_SHA, prompt_cache=PROMPT_CACHE,
            model=config.AGENT_MODEL, **(trace.get("metadata") or {}))
    t0 = time.perf_counter()
    error = None
    try:
        out = graph.invoke({"messages": [HumanMessage(question)]},
                           {"recursion_limit": RECURSION_LIMIT, "callbacks": callbacks, "metadata": metadata})
        msgs = out["messages"]
    except GraphRecursionError:
        msgs, error = [], "loop_limit"
    if trace_id is None and metadata:
        trace_id = lf.last_trace_id
    # input은 캐시 읽기·쓰기를 포함한 합계(langchain-anthropic 기준)이고, cache_read·cache_write는 그 안의 몫이다.
    calls, tokens = [], {"input": 0, "output": 0, "llm_calls": 0, "cache_read": 0, "cache_write": 0}
    results = {}
    for m in msgs:
        if isinstance(m, ToolMessage):
            results[m.tool_call_id] = _text(m.content)
        if isinstance(m, AIMessage):
            tokens["llm_calls"] += 1
            u = m.usage_metadata or {}
            tokens["input"] += u.get("input_tokens", 0)
            tokens["output"] += u.get("output_tokens", 0)
            d = u.get("input_token_details") or {}
            tokens["cache_read"] += d.get("cache_read") or 0
            # langchain-anthropic은 TTL별 값이 있으면 쓰기 토큰을 ephemeral_5m/1h에 넣고 cache_creation을 0으로 둔다.
            tokens["cache_write"] += sum(d.get(k) or 0 for k in
                                         ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"))
            calls += [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls]
    for c in calls:
        c["result"] = results.get(c["id"])
    final = next((_text(m.content) for m in reversed(msgs) if isinstance(m, AIMessage)
                  and not m.tool_calls), None)
    return {"question": question, "answer": final, "tool_calls": calls,
            "tools_called": [c["name"] for c in calls], "tokens": tokens, "error": error,
            "latency_s": round(time.perf_counter() - t0, 2),
            "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA, "prompt_cache": PROMPT_CACHE,
            "trace_id": trace_id}


def main():
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
    r = ask(a.question, trace={"name": "cli"})
    tracing.flush()
    if a.trace:
        for c in r["tool_calls"]:
            print(f"[{c['name']}] {json.dumps(c['args'], ensure_ascii=False)}")
            print("   →", (c["result"] or "")[:300])
    print(r["answer"] if r["answer"] else f"(답 없음: {r['error']})")
    print(f"\n도구 {r['tools_called']} | 토큰 {r['tokens']} | {r['latency_s']}s | 트레이스 {r['trace_id']}")


if __name__ == "__main__":
    main()
