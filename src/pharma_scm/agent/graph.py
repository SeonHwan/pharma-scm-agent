"""LangGraph 단일 에이전트: agent(LLM) ⇄ tools 루프. 도구 3개를 한 에이전트에 모두 준다."""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .. import config
from .prompt import SYSTEM_PROMPT
from .tools import TOOLS

MAX_TOOL_ROUNDS = 8
# agent→tools 한 번이 2 step. 마지막 agent 호출 1 step을 더한다.
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 2 + 1


def make_llm():
    import os

    config.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(".env에 ANTHROPIC_API_KEY가 없다")
    return ChatAnthropic(model=config.AGENT_MODEL, max_tokens=2048,
                         timeout=60, max_retries=2)


def build_graph(llm=None):
    llm = llm or make_llm()
    bound = llm.bind_tools(TOOLS)

    def agent(state):
        return {"messages": [bound.invoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()
