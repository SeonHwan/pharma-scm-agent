"""자동 채점기. 규칙은 docs/eval_protocol.md에 사전 등록돼 있다(결과를 보기 전에 확정).

에이전트 답의 마지막 줄은 `최종 답: ...` 형식이어야 한다. 그 줄만 채점한다.
"""

import re

STATUS_LABELS = ["결품 중", "단종 예정", "해소됨", "기록 없음"]
_FINAL = re.compile(r"^\s*최종 답\s*:\s*(.+?)\s*$", re.MULTILINE)
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_SKU = re.compile(r"SKU-\d{3}")
_SEC = re.compile(r"SOP-\d{2}-\d")
DECIMAL_TOL = 0.05


def final_line(text):
    m = _FINAL.findall(text or "")
    return m[-1] if m else None


def _numbers(s):
    return [float(x.replace(",", "")) for x in _NUM.findall(s)]


def _num_ok(got, gold):
    if isinstance(gold, int):
        return got == gold
    return abs(got - gold) <= DECIMAL_TOL + 1e-9


def _status_in(s):
    return [lab for lab in STATUS_LABELS if lab in s]


def grade_answer(q, answer_text):
    """반환: (pass, reason). format 오류는 reason이 'format:'으로 시작한다."""
    fin = final_line(answer_text)
    if fin is None:
        return False, "format: 최종 답 줄 없음"
    g = q["gold"]
    kind = g["kind"]
    if kind == "refusal":
        return ("거절" in fin), ("" if "거절" in fin else "거절하지 않음")
    if kind == "number":
        nums = _numbers(fin)
        if len(nums) != 1:
            return False, f"format: 숫자 {len(nums)}개"
        ok = _num_ok(nums[0], g["value"])
        return ok, "" if ok else f"숫자 불일치 got={nums[0]} gold={g['value']}"
    if kind == "set":
        got = set(_SKU.findall(fin))
        gold = set(g["value"])
        if not got and "없음" in fin and not gold:
            return True, ""
        return got == gold, "" if got == gold else f"집합 불일치 got={sorted(got)} gold={sorted(gold)}"
    if kind == "status":
        labs = _status_in(fin)
        if len(labs) != 1:
            return False, f"format: 상태 라벨 {len(labs)}개"
        return labs[0] == g["value"], "" if labs[0] == g["value"] else f"상태 불일치 got={labs[0]}"
    if kind == "status_number":
        labs, nums = _status_in(fin), _numbers(fin)
        if len(labs) != 1 or len(nums) != 1:
            return False, f"format: 라벨 {len(labs)}개, 숫자 {len(nums)}개"
        if labs[0] != g["value"]["status"]:
            return False, f"상태 불일치 got={labs[0]}"
        ok = _num_ok(nums[0], g["value"]["number"])
        return ok, "" if ok else f"숫자 불일치 got={nums[0]}"
    if kind == "sections":
        got = set(_SEC.findall(fin))
        ok = g["value"] in got and len(got) <= 2
        return ok, "" if ok else f"섹션 불일치 got={sorted(got)} gold={g['value']}"
    raise ValueError(kind)


def grade_tools(q, tools_called):
    """정답 도구가 하나뿐인 질문에서만 채점한다. 반환: (exact, hit) 또는 (None, None)."""
    exp = q["expected_tools"]
    if q["type"] == "E" or len(exp) != 1:
        return None, None
    called = set(tools_called)
    return called == set(exp), exp[0] in called


def grade(q, answer_text, tools_called):
    ok, reason = grade_answer(q, answer_text)
    exact, hit = grade_tools(q, tools_called)
    return {"id": q["id"], "type": q["type"], "pass": ok, "reason": reason,
            "format_ok": not reason.startswith("format:"), "tool_exact": exact, "tool_hit": hit}
