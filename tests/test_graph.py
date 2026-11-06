from langchain_core.messages import AIMessage

from pharma_scm.agent.graph import build_graph
from pharma_scm.agent.run import ask

from .conftest import FakeChat


def call(sql, i=1):
    return AIMessage(content="", tool_calls=[{"id": f"c{i}", "name": "query_db", "args": {"sql": sql}}])


def test_tool_round_trip_and_rejected_sql_is_reported_to_model():
    """위험한 SQL은 실행되지 않고 '거부됨' 결과가 모델에게 돌아가며, 모델이 그걸 보고 답을 이어 간다."""
    g = build_graph(FakeChat(script=[call("DROP TABLE products"), AIMessage(content="최종 답: 거절")]))
    r = ask("x", g)
    assert r["tools_called"] == ["query_db"]
    assert r["tool_calls"][0]["result"].startswith("오류(거부됨)")
    assert r["tokens"]["llm_calls"] == 2


def test_loop_limit_is_reported_not_raised():
    """모델이 도구 호출만 계속 반복해도 상한에서 멈추고 loop_limit로 보고한다(무한 호출·비용 폭주 방지)."""
    g = build_graph(FakeChat(script=[call("DROP TABLE x", i) for i in range(60)]))
    r = ask("loop", g)
    assert r["error"] == "loop_limit" and r["answer"] is None
