"""평가셋 v3: 단일 에이전트가 실제로 틀릴 만한 문항(docs/multi_agent_protocol.md).

- X: 여러 도구·여러 대상. 외부 결품 상태(get_shortage, 성분마다 호출)와 DB 조건을 합친다. 정답은 SKU 집합 등.
- Y: 규정과 데이터를 함께. DB로 구한 SKU 집합(또는 수치)과 근거 규정 섹션을 둘 다 맞혀야 한다.
- Z: 문서 모순. 규정 문서끼리 값이 다른 주제에서 모순되는 섹션을 모두 밝혀야 한다.

정답은 DB와 결품 스냅샷에서 계산한다(결품 상태 규칙은 v1과 같다: 결품 중 > 단종 예정 > 해소됨 > 기록 없음).
--pilot은 판정에 쓰지 않는 파일럿 문항(eval/questions_v3_pilot.jsonl)을 만든다.

실행: uv run python -m pharma_scm.evalset.build_evalset_v3 --pilot
"""

import argparse
import json

import psycopg

from .. import config

AO = config.AS_OF.isoformat()
AVAIL = f"l.lot_status = 'available' AND l.expiry_date >= DATE '{AO}'"
STATUS_OF = {"Current": "결품 중", "To Be Discontinued": "단종 예정", "Resolved": "해소됨"}
PILOT_OUT = config.ROOT / "eval" / "questions_v3_pilot.jsonl"
# 두 번째 파일럿: 90개 전 품목의 결품 상태를 확인해야 해서 도구 결과가 약 4만 토큰 쌓이는 문항(컨텍스트 부하)
PILOT2_OUT = config.ROOT / "eval" / "questions_v3_pilot2.jsonl"


def load_facts(conn):
    """SKU별 속성, 가용 재고, 결품 상태."""
    stat = {}
    for name, status in conn.execute("SELECT generic_name, status FROM shortage_events"):
        stat.setdefault(name, set()).add(status)

    def label(name):
        return next((STATUS_OF[k] for k in ("Current", "To Be Discontinued", "Resolved")
                     if k in stat.get(name, set())), "기록 없음")

    rows = conn.execute(
        "SELECT p.sku, p.generic_name, p.storage_condition, p.safety_stock, p.supplier_id, s.country, "
        f"coalesce(sum(l.quantity) FILTER (WHERE {AVAIL}), 0) "
        "FROM products p JOIN suppliers s USING (supplier_id) LEFT JOIN inventory_lots l ON l.sku = p.sku "
        "GROUP BY p.sku, s.country ORDER BY 1").fetchall()
    keys = ("sku", "generic_name", "storage", "safety_stock", "supplier_id", "country", "avail")
    facts = [dict(zip(keys, r)) for r in rows]
    for f in facts:
        f["label"] = label(f["generic_name"])
        f["low"] = f["avail"] < f["safety_stock"]
    return facts


def skus(conn, sql):
    return sorted(r[0] for r in conn.execute(sql))


def pilot(conn):
    f = load_facts(conn)
    lab = {x["sku"]: x["label"] for x in f}
    exp30 = skus(conn, f"SELECT DISTINCT l.sku FROM inventory_lots l WHERE {AVAIL} AND l.expiry_date <= DATE '2026-12-01'")
    late = skus(conn, f"SELECT DISTINCT sku FROM purchase_orders WHERE status = 'open' AND expected_date < DATE '{AO}'")
    quar = skus(conn, "SELECT DISTINCT sku FROM inventory_lots WHERE lot_status = 'quarantine'")
    zero = [x["sku"] for x in f if x["avail"] == 0]
    zero_labels = {lab[s] for s in zero}
    assert len(zero_labels) == 1, zero_labels
    fmt_set = "(최종 답: SKU 목록)"
    items = [
        ("X", "외부 결품 기록상 '결품 중'인 성분의 냉장 보관 품목 가운데, 가용 재고가 안전재고보다 적은 SKU를 모두 알려줘. "
         + fmt_set, ["query_db", "get_shortage"],
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["storage"] == "냉장" and x["label"] == "결품 중" and x["low"])}),
        ("X", "가용 재고가 안전재고보다 적은 품목 가운데 외부 결품 상태가 '단종 예정'인 SKU를 모두 알려줘. " + fmt_set,
         ["query_db", "get_shortage"],
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["low"] and x["label"] == "단종 예정")}),
        ("X", "국내(KR) 공급사가 공급하는 품목 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 알려줘. " + fmt_set,
         ["query_db", "get_shortage"],
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["country"] == "KR" and x["label"] == "결품 중")}),
        ("X", "공급사 SUP-08이 공급하는 품목 가운데 외부 결품 상태가 '단종 예정'인 SKU를 모두 알려줘. " + fmt_set,
         ["query_db", "get_shortage"],
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["supplier_id"] == "SUP-08" and x["label"] == "단종 예정")}),
        ("X", "가용 재고가 하나도 없는 SKU들의 외부 결품 상태는 모두 같아. 그 상태와 해당 SKU 수를 알려줘. (최종 답: 상태, 숫자)",
         ["query_db", "get_shortage"],
         {"kind": "status_number", "value": {"status": zero_labels.pop(), "number": len(zero)}}),
        ("X", "예상 입고일이 기준일보다 앞서는데 아직 입고되지 않은 발주가 있는 SKU 가운데, 외부 결품 상태가 '결품 중'인 SKU를 모두 알려줘. "
         + fmt_set, ["query_db", "get_shortage"],
         {"kind": "set", "value": [s for s in late if lab[s] == "결품 중"]}),
        ("Y", "기준일부터 2026-12-01까지(그날 포함) 유통기한이 끝나는 가용 로트를 가진 SKU를 모두 알려주고, 이런 로트를 어떻게 "
         "분류하고 처리하는지 근거 규정 섹션도 알려줘. (최종 답: SKU 목록, 섹션 id)", ["query_db", "search_sop"],
         {"kind": "set_section", "value": {"skus": exp30, "section": "SOP-03-2"}}),
        ("Y", "격리 상태 로트가 있는 SKU 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 알려주고, 격리 로트를 최대 얼마나 유지할 수 "
         "있는지 근거 규정 섹션도 알려줘. (최종 답: SKU 목록, 섹션 id)", ["query_db", "get_shortage", "search_sop"],
         {"kind": "set_section", "value": {"skus": [s for s in quar if lab[s] == "결품 중"], "section": "SOP-04-3"}}),
        ("Y", "예상 입고일이 기준일보다 앞서는데 아직 입고되지 않은 발주가 있는 SKU는 몇 개야? 그리고 예상 입고일 당일에 입고되지 않은 "
         "발주를 지연으로 보는지 근거 규정 섹션도 알려줘. (최종 답: 숫자, 섹션 id)", ["query_db", "search_sop"],
         {"kind": "number_section", "value": {"number": len(late), "section": "SOP-06-3"}}),
        ("Z", "창고 보관 구역의 냉장 온도 기록은 몇 년 보관해야 해? 규정 문서끼리 기간이 다르면 서로 다른 섹션을 모두 적어줘. "
         "(최종 답: 섹션 id 목록)", ["search_sop"],
         {"kind": "sections_conflict", "value": {"required": ["SOP-02-1", "SOP-22-2"], "allowed": ["SOP-11-9", "SOP-15-4"]}}),
    ]
    return [{"id": f"P{i:02d}", "type": t, "question": text, "expected_tools": tools, "gold": gold}
            for i, (t, text, tools, gold) in enumerate(items, 1)]


def pilot2(conn):
    f = load_facts(conn)
    counts = {}
    for x in f:
        counts[x["label"]] = counts.get(x["label"], 0) + 1
    rec = {name: n for name, n in conn.execute("SELECT generic_name, count(*) FROM shortage_events GROUP BY 1")}
    ranked = sorted(((rec.get(x["generic_name"], 0), x["sku"]) for x in f), reverse=True)
    assert ranked[0][0] > ranked[1][0], "결품 기록 건수 1위가 동률"
    items = [
        ("L", "전체 품목(SKU) 가운데 외부 결품 상태가 '해소됨'인 SKU를 모두 알려줘. (최종 답: SKU 목록)",
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["label"] == "해소됨")}),
        ("L", "전체 품목(SKU)을 외부 결품 상태(결품 중/단종 예정/해소됨/기록 없음)별로 나누면 각각 몇 개야? "
         "(최종 답: 결품 중 N, 단종 예정 N, 해소됨 N, 기록 없음 N)",
         {"kind": "status_counts", "value": counts}),
        ("L", "외부 결품 기록이 하나도 없는 품목 가운데 가용 재고가 안전재고보다 적은 SKU를 모두 알려줘. (최종 답: SKU 목록)",
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["label"] == "기록 없음" and x["low"])}),
        ("L", "전체 품목 가운데 외부 결품 기록(포장 단위 NDC 기준) 건수가 가장 많은 품목의 SKU와 그 건수는? (최종 답: SKU, 숫자)",
         {"kind": "sku_number", "value": {"skus": [ranked[0][1]], "number": ranked[0][0]}}),
        ("L", "외부 결품 상태가 '해소됨'이거나 '기록 없음'인 품목들의 가용 재고 합계는? (최종 답: 숫자)",
         {"kind": "number", "value": int(sum(x["avail"] for x in f if x["label"] in ("해소됨", "기록 없음")))}),
    ]
    return [{"id": f"Q{i:02d}", "type": t, "question": text, "expected_tools": ["query_db", "get_shortage"], "gold": gold}
            for i, (t, text, gold) in enumerate(items, 1)]


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--pilot2", action="store_true")
    a = ap.parse_args()
    out = PILOT_OUT if a.pilot else PILOT2_OUT
    with psycopg.connect(config.ADMIN_DSN) as conn:
        items = pilot(conn) if a.pilot else pilot2(conn)
    out.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in items), encoding="utf-8")
    print(f"파일럿 {len(items)}문항 저장: {out.relative_to(config.ROOT)}")
    for q in items:
        print(q["id"], q["type"], json.dumps(q["gold"]["value"], ensure_ascii=False)[:100])


if __name__ == "__main__":
    main()
