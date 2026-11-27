import json
from pathlib import Path

import psycopg
import pytest

from pharma_scm import config
from pharma_scm.evalset.grader import _num_ok

QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl"


def _gold_sql_rows():
    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if "gold_sql" in r]


# 정답표가 DB와 어긋나면 에이전트가 맞아도 오답 처리됨. gold_sql을 읽기 전용 계정으로 다시 실행해 gold와 대조.
@pytest.mark.parametrize("q", _gold_sql_rows(), ids=lambda q: q["id"])
def test_gold_sql_matches_gold(needs_db, q):
    with psycopg.connect(config.RO_DSN) as conn:
        rows = conn.execute(q["gold_sql"]).fetchall()
    gold = q["gold"]
    if gold["kind"] == "number":
        assert len(rows) == 1 and len(rows[0]) == 1, f"{q['id']}: 값 하나를 기대했는데 {rows}"
        # psycopg는 숫자를 Decimal로 돌려줌. _num_ok의 소수 경로(float 뺄셈)에 맞춰 float으로 바꿈.
        got = float(rows[0][0])
        assert _num_ok(got, gold["value"]), f"{q['id']}: DB={got} gold={gold['value']}"
    elif gold["kind"] == "set":
        got = {r[0] for r in rows}
        assert got == set(gold["value"]), f"{q['id']}: DB={sorted(got)} gold={sorted(gold['value'])}"
    else:
        pytest.fail(f"{q['id']}: 알 수 없는 gold.kind={gold['kind']}")
