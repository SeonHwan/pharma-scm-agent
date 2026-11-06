import io
import json
import logging
import time

import anthropic
import httpx
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


def test_health_needs_no_auth():
    assert make().get("/health").json() == {"status": "ok"}


def test_ready_ok_and_not_ready():
    s = Settings(api_keys=("k",))
    c = TestClient(create_app(s, agent_factory=lambda: (lambda q, cb: ok_result()), ready_checks=lambda: {"db": "ok"}))
    assert c.get("/ready").status_code == 200
    c = TestClient(create_app(s, agent_factory=lambda: (lambda q, cb: ok_result()),
                              ready_checks=lambda: {"db": "error:OperationalError"}))
    r = c.get("/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"


def test_health_stays_ok_when_not_ready():
    s = Settings(api_keys=("k",))
    c = TestClient(create_app(s, agent_factory=lambda: (lambda q, cb: ok_result()), ready_checks=lambda: {"db": "error:x"}))
    assert c.get("/health").status_code == 200 and c.get("/ready").status_code == 503


def test_refuses_to_start_without_api_key():
    with pytest.raises(RuntimeError):
        create_app(Settings(api_keys=()), agent_factory=lambda: (lambda q, cb: ok_result()))


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_ask_requires_valid_key(headers):
    r = make().post("/ask", json={"question": "q"}, headers=headers)
    assert r.status_code == 401 and err(r)["code"] == "unauthorized"


def test_ask_success_shape_and_second_key():
    c = make()
    for k in ("test-key-1", "test-key-2"):
        r = c.post("/ask", json={"question": "  재고는?  "}, headers={"X-API-Key": k})
        assert r.status_code == 200
        b = r.json()
        assert b["answer"].endswith("최종 답: 9") and b["tools_called"] == ["query_db"]
        assert b["prompt_version"] and b["request_id"] == r.headers["X-Request-ID"]


def test_question_is_stripped_before_reaching_agent():
    seen = []
    c = make(ask_fn=lambda q, cb: seen.append(q) or ok_result())
    c.post("/ask", json={"question": "  hi  "}, headers=KEY)
    assert seen == ["hi"]


def test_request_id_is_echoed_or_generated():
    c = make()
    r = c.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    r = c.get("/health", headers={"X-Request-ID": "bad id!\n"})
    assert r.headers["X-Request-ID"] != "bad id!" and len(r.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "}, {"question": "x" * 1001},
                                  {"question": 5}])
def test_validation_errors_use_common_format_and_do_not_echo_input(body):
    r = make().post("/ask", json=body, headers=KEY)
    assert r.status_code == 422 and err(r)["code"] == "bad_request" and err(r)["request_id"]
    assert "x" * 50 not in r.text


def test_unknown_route_uses_error_format():
    r = make().get("/nope")
    assert r.status_code == 404 and err(r)["code"] == "not_found"


def test_timeout_returns_504():
    c = make(ask_fn=lambda q, cb: time.sleep(1.0) or ok_result(), ask_timeout_s=0.1)
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 504 and err(r)["code"] == "timeout"


def test_loop_limit_has_its_own_code():
    c = make(ask_fn=lambda q, cb: ok_result(answer=None, error="loop_limit"))
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 508 and err(r)["code"] == "loop_limit"


def test_empty_answer_has_its_own_code():
    c = make(ask_fn=lambda q, cb: ok_result(answer=""))
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 502 and err(r)["code"] == "empty_answer"


def _raise(exc):
    def f(q, cb):
        raise exc
    return f


def test_upstream_errors_are_mapped():
    req = httpx.Request("POST", "https://example.invalid")
    cases = [
        (anthropic.APIConnectionError(request=req), 502, "upstream_error"),
        (anthropic.APITimeoutError(request=req), 502, "upstream_error"),
        (anthropic.RateLimitError("x", response=httpx.Response(429, request=req), body=None),
         503, "upstream_rate_limited"),
        (anthropic.InternalServerError("x", response=httpx.Response(500, request=req), body=None),
         502, "upstream_error"),
    ]
    for exc, status, code in cases:
        r = make(ask_fn=_raise(exc)).post("/ask", json={"question": "q"}, headers=KEY)
        assert r.status_code == status and err(r)["code"] == code, exc


def test_internal_error_does_not_leak_details():
    c = make(ask_fn=_raise(RuntimeError("secret connection string")))
    r = c.post("/ask", json={"question": "q"}, headers=KEY)
    assert r.status_code == 500 and err(r)["code"] == "internal_error"
    assert "secret" not in r.text


def test_rate_limit_per_key_with_retry_after():
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


def test_auth_failures_are_logged_with_status(log_lines):
    make().post("/ask", json={"question": "q"}, headers={"X-Request-ID": "rid-2"})
    assert any(x["msg"] == "request" and x["status"] == 401 and x["request_id"] == "rid-2"
               for x in log_lines())


def test_default_ready_check_reports_db_failure_without_details(monkeypatch):
    from pharma_scm import config
    from pharma_scm.api.app import default_ready_checks

    monkeypatch.setattr(config, "RO_DSN", "postgresql://u:p@127.0.0.1:5999/x")
    checks = default_ready_checks()
    assert checks["db_readonly"] == "error:OperationalError"


def test_agent_factory_runs_once_even_across_requests():
    calls = []

    def factory():
        calls.append(1)
        return lambda q, cb: ok_result()

    c = TestClient(create_app(Settings(api_keys=("k",)), agent_factory=factory))
    for _ in range(3):
        assert c.post("/ask", json={"question": "q"}, headers={"X-API-Key": "k"}).status_code == 200
    assert calls == [1]


def test_factory_failure_stops_startup_instead_of_first_request():
    def broken():
        raise RuntimeError("모델 키 없음")

    app = create_app(Settings(api_keys=("k",)), agent_factory=broken)
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass
