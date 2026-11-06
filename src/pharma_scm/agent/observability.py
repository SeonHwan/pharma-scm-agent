"""LLM 호출과 도구 호출의 단계별 소요 시간을 모으는 LangChain 콜백."""

import threading
import time
from collections import OrderedDict

from langchain_core.callbacks import BaseCallbackHandler
from typing import Any
from uuid import UUID
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult


class TimingCallback(BaseCallbackHandler):
    """요청 하나당 인스턴스 하나. stages = [{"stage": "llm"|"tool", "name": ..., "ms": ..., "error": bool}]"""

    def __init__(self) -> None:
        self.stages = []
        self._open = OrderedDict()
        self._lock = threading.Lock()

    def _start(self, run_id: UUID, stage: str, name: str | None) -> None:
        with self._lock:
            self._open[run_id] = (stage, name, time.perf_counter())

    def _end(self, run_id: UUID, error: bool = False) -> None:
        with self._lock:
            started = self._open.pop(run_id, None)
            if started is None:
                return
            stage, name, t0 = started
            self.stages.append({"stage": stage, "name": name,
                                "ms": round((time.perf_counter() - t0) * 1000, 1), "error": error})

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[BaseMessage]],
                            *, run_id: UUID, **kwargs: Any) -> None:
        self._start(run_id, "llm", None)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=True)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: UUID,
                      **kwargs: Any) -> None:
        self._start(run_id, "tool", kwargs.get("name") or (serialized or {}).get("name"))

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=True)
