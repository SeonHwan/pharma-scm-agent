import json

from pharma_scm.agent import tools as T


def test_query_db_rejected_without_touching_db():
    """위험한 SQL은 DB에 닿기 전에 거부 메시지로 돌려줌(DB 불필요)."""
    assert T.run_query_db("DROP TABLE products").startswith("오류(거부됨)")


def test_query_db_returns_rows(needs_db):
    """정상 조회는 실제 데이터(products 90행)를 정확히 돌려줌."""
    d = json.loads(T.run_query_db("SELECT count(*) AS n FROM products"))
    assert d["rows"] == [[90]] and d["columns"] == ["n"] and d["truncated"] is False


def test_query_db_truncates_at_200_rows(needs_db):
    """결과가 많아도 200행에서 자르고 잘렸다고 표시(모델 입력 폭주·비용 방지)."""
    d = json.loads(T.run_query_db("SELECT order_item_id FROM sales_orders"))
    assert d["row_count"] == 200 and d["truncated"] is True


def test_get_shortage_current(needs_db):
    """결품 중인 품목은 '결품 중'과 기록 수를 정확히 돌려줌."""
    d = json.loads(T.run_get_shortage("Clonazepam Tablet"))
    assert d["found"] and d["summary_status"] == "결품 중" and d["record_count"] == 40


def test_get_shortage_no_record(needs_db):
    """외부 기록이 없는 품목은 '해소됨'이 아니라 '기록 없음'으로 구분해 알림(잘못된 안심 방지)."""
    d = json.loads(T.run_get_shortage("Gabapentin Capsule"))
    assert d["found"] is False and d["summary_status"] == "기록 없음"
