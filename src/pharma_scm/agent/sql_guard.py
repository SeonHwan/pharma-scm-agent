"""query_db에 들어온 SQL을 실행 전에 검사한다. DB 계정(pharma_ro)의 권한 제한과 별개의 1차 방어선."""

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"products", "sales_orders", "suppliers", "purchase_orders", "inventory_lots"}
_FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter,
                    exp.Command, exp.Copy, exp.Into, exp.Merge, exp.Set, exp.Lock)
_FORBIDDEN_FUNC_PREFIX = ("pg_", "lo_", "dblink", "set_config", "current_setting", "txid_")


class SqlRejected(ValueError):
    pass


def validate(sql: str) -> str:
    """통과하면 정규화된 SQL 문자열을, 아니면 SqlRejected를 낸다."""
    try:
        stmts = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as e:
        raise SqlRejected(f"SQL을 해석할 수 없다: {str(e)[:120]}") from e
    if len(stmts) != 1:
        raise SqlRejected("문장은 정확히 하나여야 한다")
    tree = stmts[0]
    if not isinstance(tree, exp.Query):
        raise SqlRejected("SELECT 문만 허용한다")
    if tree.find(*_FORBIDDEN_NODES):
        raise SqlRejected("데이터를 바꾸거나 외부로 내보내는 구문은 허용하지 않는다")
    ctes = {c.alias.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if t.db or t.catalog:
            raise SqlRejected("스키마를 붙인 테이블 이름은 허용하지 않는다")
        name = t.name.lower()
        if name not in ALLOWED_TABLES and name not in ctes:
            raise SqlRejected(f"허용되지 않은 테이블: {t.name}")
    for f in tree.find_all(exp.Func):
        name = (f.name or "").lower()
        if name.startswith(_FORBIDDEN_FUNC_PREFIX):
            raise SqlRejected(f"허용되지 않은 함수: {f.name}")
    return tree.sql(dialect="postgres", comments=False)
