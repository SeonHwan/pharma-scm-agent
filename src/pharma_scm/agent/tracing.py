"""Langfuse 트레이싱(선택). 키가 없으면 아무것도 하지 않는다(CI, 시험, 배포는 영향 없음).

- 에이전트 한 번 실행 = 트레이스 하나. LLM 호출(토큰, 캐시 토큰), 도구 호출(입력, 결과, 시간)이 그 안에 들어간다.
- 트레이스 ID는 외부 ID(API 요청 ID, 평가 run_id+문항 ID)에서 결정적으로 만든다. 로그나 평가 결과의 ID로 트레이스를 찾을 수 있다.
- 평가 채점 결과는 트레이스에 점수로 붙인다(score_grade).

키: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL(.env). LANGFUSE_TRACING_ENABLED=false면 끈다.
API는 설치된 langfuse 5.2.0 소스로 확인했다(docs/langfuse.md).
"""

import os

from .. import config


def enabled():
    config.load_env()
    return (bool(os.environ.get("LANGFUSE_PUBLIC_KEY")) and bool(os.environ.get("LANGFUSE_SECRET_KEY"))
            and os.environ.get("LANGFUSE_TRACING_ENABLED", "true").lower() != "false")


def trace_id_for(external_id):
    """외부 ID에서 Langfuse 트레이스 ID(32자리 16진수)를 결정적으로 만든다."""
    from langfuse import Langfuse

    return Langfuse.create_trace_id(seed=external_id)


def handler(trace_id=None):
    """LangChain 콜백. 꺼져 있으면 None."""
    if not enabled():
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler(trace_context={"trace_id": trace_id} if trace_id else None)


def run_metadata(name, session_id=None, tags=None, **metadata):
    """graph.invoke 설정의 metadata. langfuse_* 키는 트레이스 이름·세션·태그가 되고 나머지는 트레이스 메타데이터가 된다."""
    out = {"langfuse_trace_name": name, **metadata}
    if session_id:
        out["langfuse_session_id"] = session_id
    if tags:
        out["langfuse_tags"] = list(tags)
    return out


def score_grade(trace_id, grade):
    """평가 채점 결과를 트레이스 점수로 붙인다. pass·format_ok는 항상, tool_exact는 채점 대상일 때만."""
    if not (enabled() and trace_id):
        return
    from langfuse import get_client

    client = get_client()
    client.create_score(name="pass", value=float(grade["pass"]), trace_id=trace_id, data_type="BOOLEAN",
                        comment=grade["reason"] or None)
    client.create_score(name="format_ok", value=float(grade["format_ok"]), trace_id=trace_id, data_type="BOOLEAN")
    if grade.get("tool_exact") is not None:
        client.create_score(name="tool_exact", value=float(grade["tool_exact"]), trace_id=trace_id,
                            data_type="BOOLEAN")


def flush():
    """보내지 않은 트레이스와 점수를 보낸다(짧게 끝나는 스크립트와 서버 종료 때)."""
    if enabled():
        from langfuse import get_client

        get_client().flush()
