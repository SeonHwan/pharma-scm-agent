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
