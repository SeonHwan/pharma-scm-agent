"""여러 모듈이 같이 쓰는 타입 별칭."""

from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

# eval/questions.jsonl의 한 줄(id, type, question, expected_tools, gold, ...)
Question = dict[str, Any]
# agent.run.ask()가 돌려주는 결과(answer, tools_called, tokens, error, ...)
AskResult = dict[str, Any]
# 에이전트를 부르는 함수: (질문, 콜백 목록) -> 결과
AgentFn = Callable[[str, list[BaseCallbackHandler]], AskResult]
