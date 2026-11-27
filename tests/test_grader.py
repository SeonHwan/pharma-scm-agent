import json

from pharma_scm import config
from pharma_scm.evalset.grader import final_line, grade_answer

QS = [json.loads(x) for x in (config.ROOT / "eval" / "questions.jsonl").read_text(
    encoding="utf-8").splitlines()]
LABELS = ["결품 중", "단종 예정", "해소됨", "기록 없음"]


def gold_text(q):
    g, k = q["gold"], q["gold"]["kind"]
    if k == "refusal":
        return "최종 답: 거절"
    if k == "number":
        return f"최종 답: {g['value']:,}"
    if k == "set":
        return "최종 답: " + (", ".join(g["value"]) or "없음")
    if k == "status":
        return f"최종 답: {g['value']}"
    if k == "status_number":
        return f"최종 답: {g['value']['status']}, {g['value']['number']:,}"
    return f"근거를 확인했다.\n최종 답: {g['value']}"


def wrong_text(q):
    g, k = q["gold"], q["gold"]["kind"]
    if k == "refusal":
        return "최종 답: 10"
    if k == "number":
        return f"최종 답: {g['value'] + 1}"
    if k == "set":
        return "최종 답: SKU-999"
    if k == "status":
        return "최종 답: " + next(x for x in LABELS if x != g["value"])
    if k == "status_number":
        return f"최종 답: {g['value']['status']}, {g['value']['number'] + 1}"
    return "최종 답: SOP-99-9"


def test_oracle_passes_all():
    """114문항 모두에서 정답 문장은 채점기를 통과(정답을 틀렸다고 하지 않음)."""
    assert [q["id"] for q in QS if not grade_answer(q, gold_text(q))[0]] == []


def test_wrong_fails_all():
    """114문항 모두에서 일부러 틀린 답은 채점기를 통과하지 못함(오답을 맞았다고 하지 않음)."""
    assert [q["id"] for q in QS if grade_answer(q, wrong_text(q))[0]] == []


def test_final_line_uses_last_and_requires_marker():
    """'최종 답:' 표지가 없으면 답으로 보지 않고, 여러 개면 마지막 것만 읽음(앞부분 본문에 속지 않음)."""
    assert final_line("최종 답: 1\n최종 답: 2") == "2"
    assert final_line("답은 2") is None


def test_number_rules():
    """숫자 정답의 허용 오차 규칙: 소수는 반올림 오차만, 정수는 소수 답을 거부, 숫자 여러 개는 거부."""
    q = {"id": "t", "type": "A", "expected_tools": ["query_db"], "gold": {"kind": "number", "value": 17.4}}
    assert grade_answer(q, "최종 답: 17.4%")[0]
    assert grade_answer(q, "최종 답: 17.45")[0]
    assert not grade_answer(q, "최종 답: 17.5")[0]
    assert not grade_answer(q, "최종 답: 17.4, 20")[0]
    qi = {"id": "t", "type": "A", "expected_tools": ["query_db"], "gold": {"kind": "number", "value": 9}}
    assert grade_answer(qi, "최종 답: 9개")[0] and not grade_answer(qi, "최종 답: 9.5")[0]
