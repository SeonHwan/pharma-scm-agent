"""평가셋 v2를 만든다(docs/eval_v2_protocol.md). v1(eval/questions.jsonl)은 그대로 둔다.

- G(새 규정 문항 126개): 검색 벤치마크에서 검증을 마친 질의(eval/rag/queries_v2_final.jsonl)를 그대로 쓴다.
  정답은 질의를 만든 섹션 id다.
- H(어려운 DB 문항 30개): 여러 테이블 조인, 날짜 구간, 지표 정의를 질문에 명시한 문항. 정답은 DB에서 SQL로 계산한다.
- 문항마다 split(dev/test)을 붙인다. 유형별로 문항 id를 시드 고정으로 섞어 절반씩 나눈다.

실행: uv run python -m pharma_scm.evalset.build_evalset_v2  → eval/questions_v2.jsonl
"""

import json
import random
from decimal import Decimal

import psycopg

from .. import config

OUT = config.ROOT / "eval" / "questions_v2.jsonl"
G_SOURCE = config.ROOT / "eval" / "rag" / "queries_v2_final.jsonl"
SEED = 20261126
AO = config.AS_OF.isoformat()
AV = f"lot_status = 'available' AND expiry_date >= DATE '{AO}'"
# SKU별 가용 재고(로트가 없거나 가용 로트가 없으면 0)와 품목 속성
STOCK = (
    "(SELECT p.sku, p.safety_stock, p.storage_condition, p.supplier_id, "
    f"coalesce(sum(l.quantity) FILTER (WHERE l.lot_status = 'available' AND l.expiry_date >= DATE '{AO}'), 0) AS avail "
    "FROM products p LEFT JOIN inventory_lots l ON l.sku = p.sku GROUP BY p.sku)"
)

# (질문, 정답 종류, 정답 SQL). 종류: int(정수), dec(질문이 요구한 자리의 소수), set(SKU 목록)
H_QUESTIONS = [
    ("냉장 보관 품목 가운데 가용 재고가 안전재고보다 적은 SKU를 모두 알려줘.", "set",
     f"SELECT sku FROM {STOCK} s WHERE storage_condition = '냉장' AND avail < safety_stock"),
    ("기준일부터 2026-12-01까지(그날 포함) 유통기한이 끝나는 가용 로트를 가진 SKU를 모두 알려줘.", "set",
     f"SELECT DISTINCT sku FROM inventory_lots WHERE {AV} AND expiry_date <= DATE '2026-12-01'"),
    ("격리 로트까지 재고로 쳐도(만료되지 않은 로트만) 안전재고보다 적은 SKU는 몇 개야?", "int",
     "SELECT count(*) FROM (SELECT p.sku, p.safety_stock, coalesce(sum(l.quantity) FILTER "
     f"(WHERE l.expiry_date >= DATE '{AO}'), 0) q FROM products p LEFT JOIN inventory_lots l ON l.sku = p.sku "
     "GROUP BY p.sku) t WHERE q < safety_stock"),
    ("아직 입고되지 않은 발주 중에서 예상 입고일이 기준일보다 이전인(이미 늦어진) 발주는 몇 건이야?", "int",
     f"SELECT count(*) FROM purchase_orders WHERE status = 'open' AND expected_date < DATE '{AO}'"),
    ("예상 입고일이 기준일 이전인데 아직 입고되지 않은 발주가 있는 SKU 가운데, 가용 재고가 안전재고보다 적은 SKU를 모두 알려줘.",
     "set",
     f"SELECT sku FROM {STOCK} s WHERE avail < safety_stock AND sku IN (SELECT sku FROM purchase_orders "
     f"WHERE status = 'open' AND expected_date < DATE '{AO}')"),
    ("2026년 7~9월 Europe 시장의 주문 수는? 주문 항목(행)이 아니라 고유한 주문(order_id) 수로 세어줘.", "int",
     "SELECT count(DISTINCT order_id) FROM sales_orders WHERE market = 'Europe' "
     "AND order_date BETWEEN '2026-07-01' AND '2026-09-30'"),
    ("2026년 7~9월 Europe 시장에서 지연 배송(late_delivery) 비율은 주문 항목(행) 기준으로 몇 %야? 소수 첫째 자리까지.", "dec",
     "SELECT round(100.0 * avg(late_delivery::int), 1) FROM sales_orders WHERE market = 'Europe' "
     "AND order_date BETWEEN '2026-07-01' AND '2026-09-30'"),
    ("2025년에 월별 판매 수량 합계가 가장 컸던 달의 판매 수량은?", "int",
     "SELECT sum(quantity) FROM sales_orders WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01' "
     "GROUP BY date_trunc('month', order_date) ORDER BY 1 DESC LIMIT 1"),
    ("2026년 10월 판매 수량 합계를 주문 상태가 CANCELED와 SUSPECTED_FRAUD인 항목을 빼고 알려줘.", "int",
     "SELECT sum(quantity) FROM sales_orders WHERE order_date >= '2026-10-01' "
     "AND order_status NOT IN ('CANCELED', 'SUSPECTED_FRAUD')"),
    ("공급사마다 입고 완료 발주의 실제 평균 리드타임(주문일→입고일)과 공급사 정보의 평균 리드타임 차이(절댓값)를 구했을 때, "
     "차이가 가장 큰 공급사의 차이는 며칠이야? 소수 첫째 자리까지.", "dec",
     "SELECT round(abs(avg(received_date - order_date) - s.lead_time_days_mean), 1) d FROM purchase_orders p "
     "JOIN suppliers s USING (supplier_id) WHERE status = 'received' GROUP BY s.supplier_id, s.lead_time_days_mean "
     "ORDER BY d DESC LIMIT 1"),
    ("국내(KR) 공급사가 공급하는 냉장 보관 품목은 몇 개야?", "int",
     "SELECT count(*) FROM products p JOIN suppliers s USING (supplier_id) "
     "WHERE s.country = 'KR' AND p.storage_condition = '냉장'"),
    ("입고 완료된 발주 중 예상 입고일보다 늦게 입고된 발주의 비율은 몇 %야? 소수 첫째 자리까지.", "dec",
     "SELECT round(100.0 * avg((received_date > expected_date)::int), 1) FROM purchase_orders WHERE status = 'received'"),
    ("공급사 SUP-08이 공급하는 품목들의 가용 재고 합계는?", "int",
     f"SELECT sum(avail) FROM {STOCK} s WHERE supplier_id = 'SUP-08'"),
    ("창고별 가용 재고 합계를 구했을 때 가장 많은 창고와 가장 적은 창고의 차이는?", "int",
     f"SELECT max(t) - min(t) FROM (SELECT warehouse, sum(quantity) t FROM inventory_lots WHERE {AV} GROUP BY 1) x"),
    ("가용 재고가 하나도 없는 SKU를 모두 알려줘.", "set",
     f"SELECT sku FROM {STOCK} s WHERE avail = 0"),
    ("2026-08-03부터 2026-10-31까지 90일 동안의 판매 수량으로 SKU별 일평균 판매량(합계÷90)을 구하고, "
     "가용 재고를 일평균 판매량으로 나눈 소진 일수가 30일 미만인 SKU를 모두 알려줘. 이 기간에 판매가 없는 SKU는 제외해.", "set",
     f"SELECT s.sku FROM {STOCK} s JOIN (SELECT sku, sum(quantity) / 90.0 d FROM sales_orders "
     "WHERE order_date BETWEEN '2026-08-03' AND '2026-10-31' GROUP BY 1) v USING (sku) WHERE avail / d < 30"),
    ("치료 분류(therapeutic_category)가 정확히 'Psychiatry'인 품목들의 2026년 판매 수량 합계는?", "int",
     "SELECT sum(o.quantity) FROM sales_orders o JOIN products p USING (sku) "
     "WHERE p.therapeutic_category = 'Psychiatry' AND o.order_date >= '2026-01-01'"),
    ("가용 로트 가운데 로트 하나의 수량이 가장 많은 로트는 어느 SKU야?", "set",
     f"SELECT sku FROM inventory_lots WHERE {AV} ORDER BY quantity DESC LIMIT 1"),
    ("창고 WH-DAE에 있는 격리 로트의 수량 합계는?", "int",
     "SELECT sum(quantity) FROM inventory_lots WHERE warehouse = 'WH-DAE' AND lot_status = 'quarantine'"),
    ("2026년 10월 주문 항목 가운데 실제 배송일수가 예정 배송일수보다 2일 이상 긴 항목은 몇 건이야?", "int",
     "SELECT count(*) FROM sales_orders WHERE order_date >= '2026-10-01' "
     "AND days_shipping_real - days_shipping_scheduled >= 2"),
    ("2026년 1~6월 Europe 시장 주문 항목의 평균 실제 배송일수는? 소수 둘째 자리까지.", "dec",
     "SELECT round(avg(days_shipping_real), 2) FROM sales_orders WHERE market = 'Europe' "
     "AND order_date BETWEEN '2026-01-01' AND '2026-06-30'"),
    ("2026년 1~10월 판매 수량 합계는 2025년 1~10월보다 몇 % 늘었거나 줄었어? 줄었으면 음수로, 소수 첫째 자리까지.", "dec",
     "SELECT round(100.0 * (sum(quantity) FILTER (WHERE order_date BETWEEN '2026-01-01' AND '2026-10-31')::numeric "
     "/ sum(quantity) FILTER (WHERE order_date BETWEEN '2025-01-01' AND '2025-10-31') - 1), 1) FROM sales_orders"),
    ("미입고 발주가 있는 SKU 가운데, 가용 재고에 그 SKU의 미입고 발주 수량을 모두 더해도 안전재고보다 적은 SKU를 모두 알려줘.",
     "set",
     f"SELECT s.sku FROM {STOCK} s JOIN (SELECT sku, sum(quantity) oq FROM purchase_orders WHERE status = 'open' "
     "GROUP BY 1) o USING (sku) WHERE avail + oq < safety_stock"),
    ("로트 상태는 available인데 유통기한이 기준일 전에 이미 지난 로트의 수량 합계는?", "int",
     f"SELECT coalesce(sum(quantity), 0) FROM inventory_lots WHERE lot_status = 'available' AND expiry_date < DATE '{AO}'"),
    ("가용 재고가 0보다 큰 SKU 가운데 안전재고 대비 가용 재고 비율(가용 재고÷안전재고)이 가장 낮은 SKU는?", "set",
     f"SELECT sku FROM {STOCK} s WHERE avail > 0 ORDER BY avail::numeric / safety_stock LIMIT 1"),
    ("공급하는 품목(SKU) 수가 가장 많은 공급사는 몇 개 품목을 공급해?", "int",
     "SELECT count(*) FROM products GROUP BY supplier_id ORDER BY 1 DESC LIMIT 1"),
    ("2026년 9월에 입고 완료된(입고일 기준) 발주의 수량 합계는?", "int",
     "SELECT sum(quantity) FROM purchase_orders WHERE status = 'received' "
     "AND received_date BETWEEN '2026-09-01' AND '2026-09-30'"),
    ("2026년 주문에서 주문(order_id) 1건당 평균 주문 항목(행) 수는? 소수 둘째 자리까지.", "dec",
     "SELECT round(count(*)::numeric / count(DISTINCT order_id), 2) FROM sales_orders WHERE order_date >= '2026-01-01'"),
    ("전체 기간에서 시장별로 배송 상태가 'Shipping canceled'인 주문 항목 비율을 구했을 때, 가장 높은 시장의 비율은 몇 %야? "
     "소수 첫째 자리까지.", "dec",
     "SELECT round(100.0 * avg((delivery_status = 'Shipping canceled')::int), 1) r FROM sales_orders "
     "GROUP BY market ORDER BY r DESC LIMIT 1"),
    ("가용 재고가 안전재고보다 적은 SKU는 몇 개야?", "int",
     f"SELECT count(*) FROM {STOCK} s WHERE avail < safety_stock"),
]


def _value(rows, kind):
    if kind == "set":
        return sorted(r[0] for r in rows)
    (v,), = rows
    if kind == "int":
        if isinstance(v, Decimal) and v != v.to_integral_value():
            raise ValueError(f"정수 문항인데 소수가 나왔다: {v}")
        return int(v)
    return float(v)


def build_h(conn):
    out = []
    for i, (text, kind, sql) in enumerate(H_QUESTIONS, 1):
        value = _value(conn.execute(sql).fetchall(), kind)
        if kind == "set" and not value:
            raise ValueError(f"H{i:03d} 정답 집합이 비었다")
        out.append({"id": f"H{i:03d}", "type": "H", "question": text, "expected_tools": ["query_db"],
                    "gold": {"kind": "set" if kind == "set" else "number", "value": value}, "gold_sql": sql})
    return out


def build_g():
    rows = [json.loads(x) for x in G_SOURCE.read_text(encoding="utf-8").splitlines()]
    return [{"id": f"G{i:03d}", "type": "G", "question": r["query"], "expected_tools": ["search_sop"],
             "gold": {"kind": "sections", "value": r["section_id"]}, "overlap": r["overlap"]}
            for i, r in enumerate(rows, 1)]


def assign_split(items):
    """유형별로 id를 시드 고정으로 섞어 앞 절반은 dev, 나머지는 test(홀수면 test가 하나 많다)."""
    rng = random.Random(SEED)
    for typ in sorted({q["type"] for q in items}):
        ids = sorted(q["id"] for q in items if q["type"] == typ)
        rng.shuffle(ids)
        dev = set(ids[: len(ids) // 2])
        for q in items:
            if q["type"] == typ:
                q["split"] = "dev" if q["id"] in dev else "test"
    return items


def main():
    with psycopg.connect(config.ADMIN_DSN) as conn:
        items = assign_split(build_g() + build_h(conn))
    OUT.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in items), encoding="utf-8")
    n = {s: sum(q["split"] == s for q in items) for s in ("dev", "test")}
    print(f"{len(items)}문항 저장: {OUT.relative_to(config.ROOT)} (dev {n['dev']}, test {n['test']})")


if __name__ == "__main__":
    main()
