from langchain_core.messages import AIMessage

from pharma_scm.agent.graph import build_graph
from pharma_scm.agent.observability import TimingCallback
from pharma_scm.agent.run import ask

from .conftest import FakeChat


def call(sql, i=1):
    return AIMessage(content="", tool_calls=[{"id": f"c{i}", "name": "query_db", "args": {"sql": sql}}])


def test_direct_answer_without_tools():
    g = build_graph(FakeChat(script=[AIMessage(content="거절합니다.\n최종 답: 거절")]))
    r = ask("복용량 알려줘", g)
    assert r["answer"].endswith("최종 답: 거절") and r["tools_called"] == [] and r["error"] is None


def test_tool_round_trip_and_rejected_sql_is_reported_to_model():
    g = build_graph(FakeChat(script=[call("DROP TABLE products"), AIMessage(content="최종 답: 거절")]))
    r = ask("x", g)
    assert r["tools_called"] == ["query_db"]
    assert r["tool_calls"][0]["result"].startswith("오류(거부됨)")
    assert r["tokens"]["llm_calls"] == 2


def test_loop_limit_is_reported_not_raised():
    g = build_graph(FakeChat(script=[call("DROP TABLE x", i) for i in range(60)]))
    r = ask("loop", g)
    assert r["error"] == "loop_limit" and r["answer"] is None


def test_timing_callback_records_llm_and_tool_stages():
    cb = TimingCallback()
    g = build_graph(FakeChat(script=[call("DROP TABLE products"), AIMessage(content="최종 답: 거절")]))
    ask("x", g, callbacks=[cb])
    kinds = [(s["stage"], s["name"]) for s in cb.stages]
    assert kinds.count(("llm", None)) == 2 and ("tool", "query_db") in kinds
    assert all(s["ms"] >= 0 and s["error"] is False for s in cb.stages)


def test_real_tool_call_against_db(needs_db):
    g = build_graph(FakeChat(script=[call("SELECT count(*) FROM products"),
                                     AIMessage(content="90개다.\n최종 답: 90")]))
    r = ask("SKU 수는?", g)
    assert '"rows": [[90]]' in r["tool_calls"][0]["result"] and r["answer"].endswith("90")
