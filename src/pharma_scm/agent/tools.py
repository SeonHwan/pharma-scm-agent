"""에이전트 도구 3개. 각 도구는 문자열(JSON)을 돌려주고, 오류도 예외 대신 문자열로 알려 모델이 고치게 한다."""

import json
import math
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

import psycopg
from langchain_core.tools import tool

from .. import config
from . import sql_guard
from typing import Any

MAX_ROWS = 200
STATUS_LABEL = {"Current": "결품 중", "To Be Discontinued": "단종 예정", "Resolved": "해소됨"}


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=_jsonable)


def run_query_db(sql: str, dsn: str | None = None) -> str:
    try:
        safe = sql_guard.validate(sql)
    except sql_guard.SqlRejected as e:
        return f"오류(거부됨): {e}"
    try:
        with psycopg.connect(dsn or config.RO_DSN, connect_timeout=5) as conn:
            conn.read_only = True
            cur = conn.execute(f"SELECT * FROM ({safe}) AS q LIMIT {MAX_ROWS + 1}")
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]
    except psycopg.Error as e:
        return f"오류(DB): {str(e).splitlines()[0][:200]}"
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return _dump({"columns": cols, "rows": [list(r) for r in rows], "row_count": len(rows),
                  "truncated": truncated})


def run_get_shortage(generic_name: str, dsn: str | None = None) -> str:
    name = generic_name.strip()
    with psycopg.connect(dsn or config.EXT_DSN, connect_timeout=5) as conn:
        conn.read_only = True
        recs = conn.execute(
            "SELECT package_ndc, status, company_name, dosage_form, initial_posting_date, "
            "update_date, discontinued_date, availability, shortage_reason, resolved_note "
            "FROM shortage_events WHERE lower(generic_name) = lower(%s) "
            "ORDER BY update_date DESC NULLS LAST, package_ndc", (name,)).fetchall()
        if not recs:
            first = name.split()[0] if name.split() else ""
            similar = [r[0] for r in conn.execute(
                "SELECT DISTINCT generic_name FROM shortage_events WHERE generic_name ILIKE %s "
                "ORDER BY 1 LIMIT 5", (first + "%",)).fetchall()] if first else []
            return _dump({"generic_name": name, "found": False, "summary_status": "기록 없음",
                          "record_count": 0, "similar_names": similar})
    cols = ["package_ndc", "status", "company_name", "dosage_form", "initial_posting_date",
            "update_date", "discontinued_date", "availability", "shortage_reason", "resolved_note"]
    counts = Counter(r[1] for r in recs)
    summary = next(STATUS_LABEL[s] for s in ("Current", "To Be Discontinued", "Resolved")
                   if counts.get(s))
    return _dump({"generic_name": name, "found": True, "summary_status": summary,
                  "record_count": len(recs), "counts_by_status": dict(counts),
                  "records": [dict(zip(cols, r)) for r in recs[:10]],
                  "records_truncated": len(recs) > 10})


def _grams(text: str) -> list[str]:
    t = re.sub(r"\s+", "", text.lower())
    return [t[i:i + 2] for i in range(len(t) - 1)]


@lru_cache(maxsize=1)
def _sop_index() -> tuple[list[Any], dict[str, float]]:
    with psycopg.connect(config.EXT_DSN, connect_timeout=5) as conn:
        conn.read_only = True
        rows = conn.execute("SELECT section_id, doc_title, title, body FROM sop_sections "
                            "ORDER BY section_id").fetchall()
    docs = [(r, Counter(_grams(f"{r[2]} {r[2]} {r[3]}"))) for r in rows]
    df = Counter(g for _r, c in docs for g in c)
    n = len(docs)
    idf = {g: math.log((n + 1) / (d + 1)) + 1 for g, d in df.items()}
    vecs = []
    for r, c in docs:
        v = {g: tf * idf[g] for g, tf in c.items()}
        vecs.append((r, v, math.sqrt(sum(x * x for x in v.values()))))
    return vecs, idf


def run_search_sop(query: str, k: int = 3) -> str:
    vecs, idf = _sop_index()
    qv = {g: tf * idf.get(g, 0.0) for g, tf in Counter(_grams(query)).items()}
    qn = math.sqrt(sum(x * x for x in qv.values())) or 1.0
    scored = []
    for r, v, vn in vecs:
        dot = sum(w * v.get(g, 0.0) for g, w in qv.items())
        scored.append((dot / (qn * vn) if vn else 0.0, r))
    scored.sort(key=lambda t: (-t[0], t[1][0]))
    return _dump({"query": query, "results": [
        {"section_id": r[0], "doc_title": r[1], "title": r[2], "body": r[3], "score": round(s, 3)}
        for s, r in scored[:k]]})


@tool
def query_db(sql: str) -> str:
    """재고·발주·판매 수치를 읽기 전용 SQL(PostgreSQL, SELECT만)로 조회한다.
    테이블: products, sales_orders, suppliers, purchase_orders, inventory_lots.
    결품 상태와 SOP 규정은 이 도구로 볼 수 없다. 결과는 최대 200행이다."""
    return run_query_db(sql)


@tool
def get_shortage(generic_name: str) -> str:
    """성분명(generic_name, products.generic_name과 같은 형식, 예: 'Clonazepam Tablet')으로
    openFDA 결품 스냅샷(2026-11-02)을 조회한다.
    summary_status는 성분 단위 판정이다: Current가 하나라도 있으면 '결품 중', 없고 To Be
    Discontinued가 있으면 '단종 예정', 없고 Resolved가 있으면 '해소됨', 기록이 없으면 '기록 없음'.
    record_count는 포장 단위(NDC) 기록 건수다. similar_names는 참고용이며 일치 기록이 아니다."""
    return run_get_shortage(generic_name)


@tool
def search_sop(query: str) -> str:
    """SOP(표준작업절차서) 섹션을 검색해 관련도 높은 상위 3개를 돌려준다.
    보관·유통기한·격리·회수·폐기·발주·결품 대응 등 규정과 절차 질문에 쓴다.
    각 결과에 section_id가 있다. 근거로 삼은 section_id를 답에 인용한다."""
    return run_search_sop(query)


TOOLS = [query_db, get_shortage, search_sop]
