import re

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

from pharma_scm.agent import run, tracing
from pharma_scm.agent.graph import build_graph
from .conftest import FakeChat


def test_disabled_by_flag_or_missing_keys(monkeypatch):
    monkeypatch.setattr(tracing.config, "load_env", lambda: None)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    assert not tracing.enabled()
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    assert tracing.enabled()
    monkeypatch.delenv("LANGFUSE_SECRET_KEY")
    assert not tracing.enabled()


def test_trace_id_is_deterministic_hex():
    a = tracing.trace_id_for("main_v1:A001")
    assert re.fullmatch(r"[0-9a-f]{32}", a) and a == tracing.trace_id_for("main_v1:A001")
    assert a != tracing.trace_id_for("main_v1:A002")


def test_run_metadata_keys():
    m = tracing.run_metadata("eval", session_id="r1", tags=["eval"], question_id="A001")
    assert m == {"langfuse_trace_name": "eval", "langfuse_session_id": "r1", "langfuse_tags": ["eval"],
                 "question_id": "A001"}


def test_ask_without_tracing_has_no_trace_id():
    g = build_graph(FakeChat(script=[AIMessage("근거\n최종 답: 1")]))
    r = run.ask("질문", g, trace={"external_id": "x"})
    assert r["trace_id"] is None and r["answer"].endswith("최종 답: 1")


class _Spy(BaseCallbackHandler):
    def __init__(self):
        self.metadata = None
        self.last_trace_id = None

    def on_chain_start(self, serialized, inputs, *, metadata=None, parent_run_id=None, **kw):
        if parent_run_id is None:
            self.metadata = metadata


def test_ask_with_tracing_passes_metadata_and_trace_id(monkeypatch):
    spy = _Spy()
    seen = {}
    monkeypatch.setattr(tracing, "enabled", lambda: True)
    monkeypatch.setattr(tracing, "handler", lambda tid=None: seen.setdefault("tid", tid) and spy or spy)
    g = build_graph(FakeChat(script=[AIMessage("최종 답: 1")]))
    r = run.ask("질문", g, trace={"name": "eval", "external_id": "r1:A001", "session_id": "r1",
                                 "metadata": {"question_id": "A001"}})
    assert r["trace_id"] == tracing.trace_id_for("r1:A001") == seen["tid"]
    assert spy.metadata["langfuse_trace_name"] == "eval" and spy.metadata["langfuse_session_id"] == "r1"
    assert spy.metadata["question_id"] == "A001" and spy.metadata["prompt_version"] == run.PROMPT_VERSION


def test_score_grade_is_noop_when_disabled():
    tracing.score_grade("0" * 32, {"pass": True, "reason": "", "format_ok": True, "tool_exact": None})


def test_multi_agent_counts_specialist_calls_and_tools(monkeypatch):
    """감독이 결품 담당에게 맡기고, 결품 담당이 get_shortage를 부르는 흐름(가짜 모델). 전문가 안의 LLM 호출과 도구가 집계된다."""
    from pharma_scm.agent import multi

    sup = FakeChat(script=[
        AIMessage("", tool_calls=[{"id": "t1", "name": "ask_shortage_specialist", "args": {"task": "A 성분 상태"}}]),
        AIMessage("A는 결품 중\n최종 답: 결품 중"),
    ])
    spec = FakeChat(script=[AIMessage("A: 결품 중(3)")])

    calls = {"n": 0}

    def fake_build(llm=None, system_prompt=None, tools=None):
        calls["n"] += 1
        return build_graph(sup if system_prompt == multi.SUPERVISOR_PROMPT else spec, system_prompt, tools)

    monkeypatch.setattr(multi, "build_graph", fake_build)
    g = multi.build_multi_graph(llm=object())
    r = run.ask("A 성분 결품 상태?", g)
    assert calls["n"] == 4  # 전문가 3 + 감독 1
    assert r["answer"].endswith("최종 답: 결품 중")
    assert r["delegations"] == ["ask_shortage_specialist"] and r["tools_called"] == []
    assert r["tokens"]["llm_calls"] == 3  # 감독 2 + 결품 담당 1
