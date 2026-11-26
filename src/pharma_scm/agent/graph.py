"""LangGraph 단일 에이전트: agent(LLM) ⇄ tools 루프. 도구 3개를 한 에이전트에 모두 준다."""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .. import config
from .prompt import SYSTEM_PROMPT
from .tools import TOOLS

MAX_TOOL_ROUNDS = 8
# 도구 정의와 시스템 프롬프트는 모든 호출에서 같으므로 캐시한다(5분). 캐시는 도구 → 시스템 순서의 앞부분이라
# 시스템 블록 끝에 표시를 두면 둘 다 캐시된다. 캐시에서 읽은 입력은 단가가 1/10이다(docs/eval_v2_protocol.md §8-1).
PROMPT_CACHE = True
# agent→tools 한 번이 2 step. 마지막 agent 호출 1 step을 더한다.
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 2 + 1


def make_llm():
    import os

    config.load_env()
    # Anthropic SDK는 전역 OpenTelemetry 트레이서가 있으면 API 호출마다 자체 span을 만든다. Langfuse(OpenTelemetry 기반)가
    # 켜져 있으면 LangChain 콜백의 기록과 같은 호출이 두 번 남아 트레이스 비용이 두 배로 합산되므로 끈다(docs/langfuse.md).
    # 클라이언트를 만들 때 읽는 값이라 ChatAnthropic보다 먼저 둔다.
    os.environ.setdefault("ANTHROPIC_OPEN_TELEMETRY", "false")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(".env에 ANTHROPIC_API_KEY가 없다")
    return ChatAnthropic(model=config.AGENT_MODEL, max_tokens=2048,
                         timeout=60, max_retries=2)


def system_message(cache=PROMPT_CACHE, text=SYSTEM_PROMPT):
    if not cache:
        return SystemMessage(text)
    return SystemMessage([{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])


def build_graph(llm=None, system_prompt=SYSTEM_PROMPT, tools=TOOLS):
    """agent ⇄ tools 루프. 기본은 단일 에이전트(도구 3개). 멀티 에이전트(multi.py)는 프롬프트와 도구를 바꿔 같은 루프를 쓴다."""
    llm = llm or make_llm()
    bound = llm.bind_tools(tools)
    system = system_message(text=system_prompt)

    def agent(state):
        return {"messages": [bound.invoke([system, *state["messages"]])]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()
