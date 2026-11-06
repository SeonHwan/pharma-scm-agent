import io
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from pharma_scm.agent.graph import build_graph
from pharma_scm.agent.run import ask
from pharma_scm.api.app import create_app
from pharma_scm.api.logging_json import JsonFormatter
from pharma_scm.api.settings import Settings

from .conftest import FakeChat

KEY = {"X-API-Key": "test-key-1"}


def ok_result(answer="근거\n최종 답: 9", tools=("query_db",), error=None):
    return {"answer": answer, "tools_called": list(tools), "error": error,
            "tokens": {"input": 10, "output": 5, "llm_calls": 2}}


def make(ask_fn=None, **kw):
    s = Settings(api_keys=("test-key-1", "test-key-2"), **kw)
    return TestClient(create_app(s, agent_factory=lambda: ask_fn or (lambda q, cb: ok_result()),
                                 ready_checks=kw.pop("ready", lambda: {"db_readonly": "ok"})))


def err(r):
    return r.json()["error"]


def _raise(exc):
    def f(q, cb):
        raise exc
    return f


def test_refuses_to_start_without_api_key():
    """API 키가 하나도 설정되지 않으면 서버가 시작되지 않는다(인증 없는 서버가 뜨는 사고 방지)."""
    with pytest.raises(RuntimeError):
        create_app(Settings(api_keys=()), agent_factory=lambda: (lambda q, cb: ok_result()))


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_ask_requires_valid_key(headers):
    """키가 없거나 틀리거나 비어 있으면 /ask는 401이다(인증 우회 방지)."""
    r = make().post("/ask", json={"question": "q"}, headers=headers)
    assert r.status_code == 401 and err(r)["code"] == "unauthorized"


def test_ask_success_shape_and_second_key():
    """등록된 키 어느 것으로든 /ask가 200과 답·도구 목록·요청 ID를 돌려준다(기본 정상 경로)."""
    c = make()
    for k in ("test-key-1", "test-key-2"):
        r = c.post("/ask", json={"question": "  재고는?  "}, headers={"X-API-Key": k})
        assert r.status_code == 200
        b = r.json()
        assert b["answer"].endswith("최종 답: 9") and b["tools_called"] == ["query_db"]
        assert b["prompt_version"] and b["request_id"] == r.headers["X-Request-ID"]


def test_timeout_returns_504():
    """에이전트가 제한 시간 안에 끝나지 않으면 504로 끊는다(무한 대기 방지)."""
    c = make(ask_fn=lambda q, cb: time.sleep(1.0) or ok_result(), ask_timeout_s=0.1)
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 504 and err(r)["code"] == "timeout"


def test_internal_error_does_not_leak_details():
    """예상 못 한 내부 오류는 500으로만 알리고, 오류 내용(예: 접속 문자열)을 응답에 싣지 않는다(정보 유출 방지)."""
    c = make(ask_fn=_raise(RuntimeError("secret connection string")))
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 500 and err(r)["code"] == "internal_error"
    assert "secret" not in r.text


def test_rate_limit_per_key_with_retry_after():
    """키별 분당 한도를 넘으면 429와 Retry-After를 주고, 다른 키와 /health는 영향받지 않는다(비용 폭주 방지)."""
    c = make(rate_limit_per_min=2)
    for _ in range(2):
        assert c.post("/ask", json={"question": "q"}, headers=KEY).status_code == 200
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 429 and err(r)["code"] == "rate_limited" and int(r.headers["Retry-After"]) >= 1
    other = c.post("/ask", json={"question": "q"}, headers={"X-API-Key": "test-key-2"})
    assert other.status_code == 200
    assert c.get("/health").status_code == 200


@pytest.fixture
def log_lines():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    lg = logging.getLogger("pharma")
    lg.addHandler(h)
    yield lambda: [json.loads(x) for x in buf.getvalue().splitlines()]
    lg.removeHandler(h)


def test_logs_are_json_with_request_id_status_and_timings(log_lines):
    """요청 로그가 JSON이고 요청 ID·상태·단계별 시간을 담으며, 질문 본문과 API 키 원문은 남기지 않는다."""
    g = build_graph(FakeChat(script=[AIMessage(content="거절\n최종 답: 거절")]))
    c = make(ask_fn=lambda q, cb: ask(q, g, callbacks=cb))
    r = c.post("/ask", json={"question": "비밀 질문 내용"}, headers={**KEY, "X-Request-ID": "rid-1"})
    assert r.status_code == 200 and r.json()["stages"][0]["stage"] == "llm"
    lines = [x for x in log_lines() if x["request_id"] == "rid-1"]
    msgs = {x["msg"]: x for x in lines}
    assert msgs["request"]["status"] == 200 and msgs["request"]["duration_ms"] >= 0
    assert msgs["ask"]["question_chars"] == 8 and msgs["ask"]["tokens"]["llm_calls"] == 1
    assert msgs["ask"]["stages"][0]["stage"] == "llm"
    assert "비밀 질문 내용" not in json.dumps(lines, ensure_ascii=False)   # 질문 본문은 로그에 남기지 않는다
    assert "test-key-1" not in json.dumps(lines)                           # 키 원문도 남기지 않는다
