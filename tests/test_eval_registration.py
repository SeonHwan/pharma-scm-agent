import hashlib
import json
from pathlib import Path

from pharma_scm.agent import prompt

ROOT = Path(__file__).resolve().parents[1]
REGISTERED = json.loads((ROOT / "eval" / "registered.json").read_text(encoding="utf-8"))

# 평가 결과는 "어떤 문항·어떤 프롬프트로 측정했는가"가 고정돼 있어야 비교할 수 있다.
# 의도한 변경이면 PROMPT_VERSION을 올리고 registered.json과 baseline을 PR로 갱신한다.
HINT = "의도한 변경이면 PROMPT_VERSION을 올리고 eval/registered.json과 baseline을 PR로 갱신한다."


def test_questions_md5():
    got = hashlib.md5((ROOT / "eval" / "questions.jsonl").read_bytes()).hexdigest()
    assert got == REGISTERED["questions_md5"], f"문항 파일이 등록값과 다르다: {got}. {HINT}"


def test_prompt_version():
    assert prompt.PROMPT_VERSION == REGISTERED["prompt_version"], (
        f"PROMPT_VERSION이 등록값과 다르다: {prompt.PROMPT_VERSION}. {HINT}"
    )


def test_prompt_sha():
    assert prompt.PROMPT_SHA == REGISTERED["prompt_sha"], (
        f"시스템 프롬프트가 등록값과 다르다: {prompt.PROMPT_SHA}. {HINT}"
    )
