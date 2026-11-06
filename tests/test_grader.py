import json

from pharma_scm import config
from pharma_scm.evalset.grader import final_line, grade, grade_answer

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
    assert [q["id"] for q in QS if not grade_answer(q, gold_text(q))[0]] == []


def test_wrong_fails_all():
    assert [q["id"] for q in QS if grade_answer(q, wrong_text(q))[0]] == []


def test_question_counts():
    assert len(QS) == 114 and len({q["id"] for q in QS}) == 114


def test_final_line_uses_last_and_requires_marker():
    assert final_line("최종 답: 1\n최종 답: 2") == "2"
    assert final_line("답은 2") is None


def test_missing_final_is_format_error():
    q = next(x for x in QS if x["gold"]["kind"] == "number")
    r = grade(q, "답은 5입니다", ["query_db"])
    assert not r["pass"] and not r["format_ok"]


def test_number_rules():
    q = {"id": "t", "type": "A", "expected_tools": ["query_db"], "gold": {"kind": "number", "value": 17.4}}
    assert grade_answer(q, "최종 답: 17.4%")[0]
    assert grade_answer(q, "최종 답: 17.45")[0]
    assert not grade_answer(q, "최종 답: 17.5")[0]
    assert not grade_answer(q, "최종 답: 17.4, 20")[0]
    qi = {"id": "t", "type": "A", "expected_tools": ["query_db"], "gold": {"kind": "number", "value": 9}}
    assert grade_answer(qi, "최종 답: 9개")[0] and not grade_answer(qi, "최종 답: 9.5")[0]


def test_sections_allows_one_extra_but_not_two():
    q = {"id": "t", "type": "C", "expected_tools": ["search_sop"],
         "gold": {"kind": "sections", "value": "SOP-03-2"}}
    assert grade_answer(q, "최종 답: SOP-03-2, SOP-03-1")[0]
    assert not grade_answer(q, "최종 답: SOP-03-2, SOP-03-1, SOP-04-1")[0]


def test_tool_grading_only_for_single_tool_questions():
    qa = next(q for q in QS if q["type"] == "A")
    assert grade(qa, gold_text(qa), ["query_db"])["tool_exact"] is True
    both = grade(qa, gold_text(qa), ["query_db", "search_sop"])
    assert both["tool_exact"] is False and both["tool_hit"] is True
    qd = next(q for q in QS if q["type"] == "D")
    assert grade(qd, gold_text(qd), ["query_db"])["tool_exact"] is None
    qe = next(q for q in QS if q["type"] == "E")
    assert grade(qe, gold_text(qe), [])["tool_exact"] is None


def test_empty_set_accepts_none_word():
    q = {"id": "t", "type": "A", "expected_tools": ["query_db"], "gold": {"kind": "set", "value": []}}
    assert grade_answer(q, "최종 답: 없음")[0]
