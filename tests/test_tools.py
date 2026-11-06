import json

from pharma_scm.agent import tools as T


def test_query_db_rejected_without_touching_db():
    assert T.run_query_db("DROP TABLE products").startswith("오류(거부됨)")


def test_query_db_returns_rows(needs_db):
    d = json.loads(T.run_query_db("SELECT count(*) AS n FROM products"))
    assert d["rows"] == [[90]] and d["columns"] == ["n"] and d["truncated"] is False


def test_query_db_truncates_at_200_rows(needs_db):
    d = json.loads(T.run_query_db("SELECT order_item_id FROM sales_orders"))
    assert d["row_count"] == 200 and d["truncated"] is True


def test_query_db_db_error_is_a_string(needs_db):
    assert T.run_query_db("SELECT nope FROM products").startswith("오류(DB)")


def test_get_shortage_current(needs_db):
    d = json.loads(T.run_get_shortage("Clonazepam Tablet"))
    assert d["found"] and d["summary_status"] == "결품 중" and d["record_count"] == 40


def test_get_shortage_is_case_insensitive(needs_db):
    assert json.loads(T.run_get_shortage("clonazepam tablet"))["found"]


def test_get_shortage_no_record(needs_db):
    d = json.loads(T.run_get_shortage("Gabapentin Capsule"))
    assert d["found"] is False and d["summary_status"] == "기록 없음"


def test_search_sop_finds_expected_sections(needs_db):
    cases = {"유통기한이 임박한 로트는 어떻게 처리해?": "SOP-03-2",
             "냉장 품목의 보관 온도 기준은?": "SOP-02-1",
             "마약류 의약품은 어디에 보관해?": "SOP-10-1"}
    for q, sec in cases.items():
        assert json.loads(T.run_search_sop(q))["results"][0]["section_id"] == sec
