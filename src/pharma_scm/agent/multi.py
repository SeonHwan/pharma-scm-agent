"""멀티 에이전트(M): 감독 에이전트가 전문가 에이전트 3개를 도구처럼 부름.

- 감독: 데이터 도구를 직접 쓰지 않음. 질문을 나눠 전문가에게 맡기고(ask_*), 받은 보고로 최종 답을 씀.
- 전문가: DB 분석가(query_db), 결품 담당(get_shortage), 규정 담당(search_sop). 각자 자기 도구 하나로 여러 단계를 처리하고
  결과를 글로 보고. 전문가는 서로의 결과를 모르므로, 필요한 정보(성분명 목록 등)는 감독이 요청에 담아 넘김.
- 단일 에이전트(S)와 비교가 공정하도록 모델, 도구, 프롬프트 문구(prompt.py의 절)는 같음. 다른 것은 구조와,
  구조 때문에 필요한 역할 설명뿐(아래 *_ROLE).
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from .graph import RECURSION_LIMIT, build_graph, make_llm
from .prompt import ANSWER_FORMAT, DATA_DICT, INTRO, REFUSAL
from .tools import get_shortage, query_db, search_sop

SUPERVISOR_ROLE = """\
## 역할: 감독
너는 데이터 도구를 직접 쓰지 않는다. 질문을 필요한 만큼 나눠 아래 전문가에게 맡기고, 받은 보고로 최종 답을 쓴다.
- 재고·발주·판매·리드타임 수치, 조건에 맞는 SKU와 성분명 목록: ask_db_analyst
- 외부 결품 상태(성분명으로 조회): ask_shortage_specialist. 여러 성분이면 성분명 목록을 한 번에 넘긴다.
- 규정·절차(어떻게 처리하나), 근거 section_id: ask_sop_specialist
- 전문가는 서로의 결과를 모른다. 앞 전문가의 결과가 필요하면(예: SKU별 성분명) 요청 문장에 그대로 넣어 넘긴다.
- 필요 없는 전문가는 부르지 않는다. 거절해야 하는 질문은 아무도 부르지 않고 거절한다.

"""

DB_ROLE = """\
너는 DB 분석가다. 감독이 맡긴 일을 query_db(읽기 전용 SQL)로 계산해 결과를 보고한다.
보고에는 계산한 값, 해당 SKU와 성분명(generic_name) 목록, 쓴 조건을 간결히 적는다. 추측하지 않는다.

"""

SHORTAGE_ROLE = """\
너는 외부 결품 담당이다. 감독이 준 성분명마다 get_shortage를 호출해 결과를 보고한다(여러 성분은 한 번에 나란히 호출해도 된다).
결품 상태는 get_shortage 결과의 summary_status(결품 중/단종 예정/해소됨/기록 없음)를 그대로 쓴다.
보고는 '성분명: 상태(결품 기록 건수 record_count)' 목록으로 빠짐없이 적는다. 데이터는 합성이고 기준일은 2026-11-01이다.
"""

SOP_ROLE = """\
너는 규정 담당이다. 감독이 맡긴 질문을 search_sop로 찾아, 근거 section_id와 해당 내용을 보고한다.
문서끼리 내용이나 수치가 다르면 서로 다른 섹션을 모두 보고한다. 검색 결과에 없는 내용은 추측하지 않는다.
"""

SUPERVISOR_PROMPT = INTRO + SUPERVISOR_ROLE + REFUSAL + ANSWER_FORMAT
DB_PROMPT = DB_ROLE + DATA_DICT
SHORTAGE_PROMPT = SHORTAGE_ROLE
SOP_PROMPT = SOP_ROLE


def _report(graph, task, config):
    """전문가 그래프에 요청 하나를 넣고 마지막 답을 보고문으로 돌려줌. 콜백(토큰 집계, Langfuse)은 config로 이어짐."""
    out = graph.invoke({"messages": [HumanMessage(task)]}, {**(config or {}), "recursion_limit": RECURSION_LIMIT})
    last = next((m for m in reversed(out["messages"]) if isinstance(m, AIMessage) and not m.tool_calls), None)
    if last is None:
        return "(보고 없음)"
    c = last.content
    return c if isinstance(c, str) else "".join(b.get("text", "") for b in c if isinstance(b, dict))


def build_multi_graph(llm=None):
    llm = llm or make_llm()
    db = build_graph(llm, DB_PROMPT, [query_db])
    shortage = build_graph(llm, SHORTAGE_PROMPT, [get_shortage])
    sop = build_graph(llm, SOP_PROMPT, [search_sop])

    @tool
    def ask_db_analyst(task: str, config: RunnableConfig) -> str:
        """DB 분석가에게 맡긴다: 재고·발주·판매·리드타임 수치, 조건에 맞는 SKU·성분명 목록. task는 완결된 요청 문장."""
        return _report(db, task, config)

    @tool
    def ask_shortage_specialist(task: str, config: RunnableConfig) -> str:
        """결품 담당에게 맡긴다: 성분명별 외부 결품 상태. task에 조회할 성분명 목록을 모두 넣는다."""
        return _report(shortage, task, config)

    @tool
    def ask_sop_specialist(task: str, config: RunnableConfig) -> str:
        """규정 담당에게 맡긴다: 규정·절차와 근거 section_id. task는 완결된 질문 문장."""
        return _report(sop, task, config)

    return build_graph(llm, SUPERVISOR_PROMPT, [ask_db_analyst, ask_shortage_specialist, ask_sop_specialist])
