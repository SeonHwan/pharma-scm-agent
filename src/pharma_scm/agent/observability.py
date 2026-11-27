"""LLM 호출과 도구 호출의 단계별 소요 시간을 모으는 LangChain 콜백."""

import threading
import time
from collections import OrderedDict

from langchain_core.callbacks import BaseCallbackHandler


class TimingCallback(BaseCallbackHandler):
    """요청 하나당 인스턴스 하나. stages = [{"stage": "llm"|"tool", "name": ..., "ms": ..., "error": bool}]"""

    def __init__(self):
        self.stages = []
        self._open = OrderedDict()
        self._lock = threading.Lock()

    def _start(self, run_id, stage, name):
        with self._lock:
            self._open[run_id] = (stage, name, time.perf_counter())

    def _end(self, run_id, error=False):
        with self._lock:
            started = self._open.pop(run_id, None)
            if started is None:
                return
            stage, name, t0 = started
            self.stages.append({"stage": stage, "name": name,
                                "ms": round((time.perf_counter() - t0) * 1000, 1), "error": error})

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._start(run_id, "llm", None)

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._end(run_id)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, error=True)

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._start(run_id, "tool", kwargs.get("name") or (serialized or {}).get("name"))

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, error=True)


class UsageCallback(BaseCallbackHandler):
    """실행 하나에서 일어난 모든 LLM 호출의 토큰과 모든 도구 호출 이름을 모음.

    멀티 에이전트는 전문가 에이전트가 도구 안에서 따로 LLM을 부르므로, 최종 메시지만 보면 그 호출이 빠짐.
    콜백은 하위 실행에도 전달되므로 단일·멀티 모두 같은 방식으로 셈. input은 캐시 읽기·쓰기를 포함한 합계.
    """

    def __init__(self):
        self.tokens = {"input": 0, "output": 0, "llm_calls": 0, "cache_read": 0, "cache_write": 0}
        self.tools = []
        self._lock = threading.Lock()

    def on_llm_end(self, response, *, run_id, **kwargs):
        for gens in response.generations:
            for g in gens:
                u = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                d = u.get("input_token_details") or {}
                with self._lock:
                    self.tokens["llm_calls"] += 1
                    self.tokens["input"] += u.get("input_tokens", 0)
                    self.tokens["output"] += u.get("output_tokens", 0)
                    self.tokens["cache_read"] += d.get("cache_read") or 0
                    # langchain-anthropic은 TTL별 값이 있으면 쓰기 토큰을 ephemeral_5m/1h에 넣고 cache_creation을 0으로 둠.
                    self.tokens["cache_write"] += sum(d.get(k) or 0 for k in (
                        "cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"))

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        with self._lock:
            self.tools.append(kwargs.get("name") or (serialized or {}).get("name"))
