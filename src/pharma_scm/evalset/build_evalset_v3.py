"""평가셋 v3: 단일 에이전트가 실제로 틀릴 만한 문항(docs/multi_agent_protocol.md).

- X: 여러 도구·여러 대상. 외부 결품 상태(get_shortage, 성분마다 호출)와 DB 조건을 합친다. 정답은 SKU 집합 등.
- Y: 규정과 데이터를 함께. DB로 구한 SKU 집합(또는 수치)과 근거 규정 섹션을 둘 다 맞혀야 한다.
- Z: 문서 모순. 규정 문서끼리 값이 다른 주제에서 모순되는 섹션을 모두 밝혀야 한다.

정답은 DB와 결품 스냅샷에서 계산한다(결품 상태 규칙은 v1과 같다: 결품 중 > 단종 예정 > 해소됨 > 기록 없음).
--pilot, --pilot2는 판정에 쓰지 않는 파일럿 문항, --main은 본 평가 30문항(eval/questions_v3.jsonl)을 만든다.

실행: uv run python -m pharma_scm.evalset.build_evalset_v3 --main
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
MAIN_OUT = config.ROOT / "eval" / "questions_v3.jsonl"
SET = "(최종 답: SKU 목록)"
SET_SEC = "(최종 답: SKU 목록, 섹션 id)"
NUM_SEC = "(최종 답: 숫자, 섹션 id)"


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


def main_set(conn):
    """본 평가 30문항(X 12, Y 8, Z 2, L 8). 파일럿과 같은 조건 조합은 쓰지 않는다."""
    f = load_facts(conn)
    lab = {x["sku"]: x["label"] for x in f}
    quar = skus(conn, "SELECT DISTINCT sku FROM inventory_lots WHERE lot_status = 'quarantine'")
    exp1231 = skus(conn, f"SELECT DISTINCT l.sku FROM inventory_lots l WHERE {AVAIL} AND l.expiry_date <= DATE '2026-12-31'")
    expired = skus(conn, f"SELECT DISTINCT sku FROM inventory_lots WHERE lot_status = 'available' AND expiry_date < DATE '{AO}'")
    zero = [x["sku"] for x in f if x["avail"] == 0]
    low = [x["sku"] for x in f if x["low"]]
    cold = [x["sku"] for x in f if x["storage"] == "냉장"]

    def pick(pool, labels):
        return sorted(s for s in pool if lab[s] in labels)

    def of(key, val):
        return [x["sku"] for x in f if x[key] == val]

    def one(sql):
        (v,), = conn.execute(sql).fetchall()
        return int(v)

    late_by_sup = conn.execute(
        f"SELECT supplier_id, count(*) n FROM purchase_orders WHERE status = 'open' AND expected_date < DATE '{AO}' "
        "GROUP BY 1 ORDER BY n DESC").fetchall()
    assert late_by_sup[0][1] > late_by_sup[1][1], "지연 발주 최다 공급사가 동률"
    rec = {name: n for name, n in conn.execute("SELECT generic_name, count(*) FROM shortage_events GROUP BY 1")}
    recs = {x["sku"]: rec.get(x["generic_name"], 0) for x in f}
    ranked = sorted(((n, s) for s, n in recs.items()), reverse=True)
    assert ranked[1][0] > ranked[2][0] and ranked[0][0] > ranked[1][0], "결품 기록 건수 2위가 동률"
    cur_by_sup = {}
    for x in f:
        if x["label"] == "결품 중":
            cur_by_sup[x["supplier_id"]] = cur_by_sup.get(x["supplier_id"], 0) + 1
    top_sup = sorted(cur_by_sup.values(), reverse=True)
    assert top_sup[0] > top_sup[1], "결품 중 품목 최다 공급사가 동률"

    X = ["query_db", "get_shortage"]
    items = [
        ("X", "냉장 보관 품목 가운데 외부 결품 상태가 '단종 예정'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(cold, {"단종 예정"})}),
        ("X", "격리 상태 로트가 있는 SKU 가운데 외부 결품 상태가 '단종 예정'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(quar, {"단종 예정"})}),
        ("X", "격리 상태 로트가 있는 SKU 가운데 외부 결품 상태가 '해소됨'이거나 '기록 없음'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(quar, {"해소됨", "기록 없음"})}),
        ("X", "2026-12-31까지(그날 포함) 유통기한이 끝나는 가용 로트를 가진 SKU 가운데 외부 결품 상태가 '단종 예정'이거나 "
         "'기록 없음'인 SKU를 모두 알려줘. " + SET, X, {"kind": "set", "value": pick(exp1231, {"단종 예정", "기록 없음"})}),
        ("X", "미국(US) 공급사가 공급하는 품목 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(of("country", "US"), {"결품 중"})}),
        ("X", "일본(JP) 공급사가 공급하는 품목 가운데 외부 결품 상태가 '단종 예정'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(of("country", "JP"), {"단종 예정"})}),
        ("X", "스위스(CH) 공급사가 공급하는 품목 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(of("country", "CH"), {"결품 중"})}),
        ("X", "공급사 SUP-09가 공급하는 품목 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(of("supplier_id", "SUP-09"), {"결품 중"})}),
        ("X", "공급사 SUP-06이 공급하는 품목 가운데 외부 결품 상태가 '해소됨'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(of("supplier_id", "SUP-06"), {"해소됨"})}),
        ("X", "공급사 SUP-11이 공급하는 품목 가운데 외부 결품 기록이 하나도 없는 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(of("supplier_id", "SUP-11"), {"기록 없음"})}),
        ("X", "가용 재고가 안전재고보다 적은 품목 가운데 외부 결품 상태가 '해소됨'인 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": pick(low, {"해소됨"})}),
        ("X", "냉장 보관 품목 가운데 외부 결품 상태가 '결품 중'인 품목은 몇 개야? (최종 답: 숫자)", X,
         {"kind": "number", "value": len(pick(cold, {"결품 중"}))}),
        ("Y", "로트 상태는 available인데 유통기한이 기준일 전에 이미 지난 로트를 가진 SKU를 모두 알려주고, 이런 로트를 폐기하려면 "
         "누구의 승인이 필요한지 근거 규정 섹션도 알려줘. " + SET_SEC, ["query_db", "search_sop"],
         {"kind": "set_section", "value": {"skus": expired, "section": "SOP-09-1"}}),
        ("Y", "2026-12-31까지(그날 포함) 유통기한이 끝나는 가용 로트를 가진 SKU 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 "
         "알려주고, 유통기한을 사내에서 연장해도 되는지 근거 규정 섹션도 알려줘. " + SET_SEC, ["query_db", "get_shortage", "search_sop"],
         {"kind": "set_section", "value": {"skus": pick(exp1231, {"결품 중"}), "section": "SOP-03-3"}}),
        ("Y", "가용 재고가 하나도 없는 SKU를 모두 알려주고, 결품 중인 품목의 영업 출고를 어떻게 제한하는지 근거 규정 섹션도 알려줘. "
         + SET_SEC, ["query_db", "search_sop"],
         {"kind": "set_section", "value": {"skus": zero, "section": "SOP-07-2"}}),
        ("Y", "냉장 보관 품목 가운데 외부 결품 상태가 '결품 중'인 SKU를 모두 알려주고, 결품이 길어질 때 대체 품목을 언제 검토하는지 "
         "근거 규정 섹션도 알려줘. " + SET_SEC, ["query_db", "get_shortage", "search_sop"],
         {"kind": "set_section", "value": {"skus": pick(cold, {"결품 중"}), "section": "SOP-07-3"}}),
        ("Y", "가용 재고가 안전재고보다 적은 SKU는 몇 개야? 그리고 안전재고를 무엇을 기준으로 정하고 언제 부족으로 분류하는지 근거 "
         "규정 섹션도 알려줘. " + NUM_SEC, ["query_db", "search_sop"],
         {"kind": "number_section", "value": {"number": len(low), "section": "SOP-06-1"}}),
        ("Y", "예상 입고일이 기준일보다 앞서는데 아직 입고되지 않은 발주가 가장 많은 공급사는 그런 발주가 몇 건이야? 그리고 반복해서 "
         "늦는 공급사를 어떤 기준으로 관리 대상으로 삼는지 근거 규정 섹션도 알려줘. " + NUM_SEC, ["query_db", "search_sop"],
         {"kind": "number_section", "value": {"number": int(late_by_sup[0][1]), "section": "SOP-08-2"}}),
        ("Y", "2026년 9월에 입고 완료된(입고일 기준) 발주는 몇 건이야? 그리고 입고할 때 어떤 서류를 확인해야 하는지 근거 규정 섹션도 "
         "알려줘. " + NUM_SEC, ["query_db", "search_sop"],
         {"kind": "number_section", "value": {
             "number": one("SELECT count(*) FROM purchase_orders WHERE status = 'received' "
                           "AND received_date BETWEEN '2026-09-01' AND '2026-09-30'"), "section": "SOP-01-1"}}),
        ("Y", "격리 상태 로트의 수량 합계는 얼마야? 그리고 어떤 로트를 격리 대상으로 보는지 근거 규정 섹션도 알려줘. " + NUM_SEC,
         ["query_db", "search_sop"],
         {"kind": "number_section", "value": {
             "number": one("SELECT sum(quantity) FROM inventory_lots WHERE lot_status = 'quarantine'"), "section": "SOP-04-1"}}),
        ("Z", "보관 창고의 온도 기록기 기록은 언제까지 보관하면 돼? 규정 문서끼리 기간이 다르면 서로 다른 섹션을 모두 적어줘. "
         "(최종 답: 섹션 id 목록)", ["search_sop"],
         {"kind": "sections_conflict", "value": {"required": ["SOP-02-1", "SOP-22-2"], "allowed": ["SOP-11-9", "SOP-15-4"]}}),
        ("Z", "재고 실사표와 재고 조정 기록은 몇 년 보관해야 해? 규정 문서끼리 기간이 다르면 서로 다른 섹션을 모두 적어줘. "
         "(최종 답: 섹션 id 목록)", ["search_sop"],
         {"kind": "sections_conflict", "value": {"required": ["SOP-16-8", "SOP-22-1"], "allowed": []}}),
        ("L", "전체 품목(SKU) 가운데 외부 결품 기록이 하나도 없는 SKU를 모두 알려줘. " + SET, X,
         {"kind": "set", "value": sorted(x["sku"] for x in f if x["label"] == "기록 없음")}),
        ("L", "외부 결품 상태가 '해소됨'인 품목들의 가용 재고 합계는? (최종 답: 숫자)", X,
         {"kind": "number", "value": int(sum(x["avail"] for x in f if x["label"] == "해소됨"))}),
        ("L", "외부 결품 상태가 '결품 중'인 품목들의 가용 재고 합계는? (최종 답: 숫자)", X,
         {"kind": "number", "value": int(sum(x["avail"] for x in f if x["label"] == "결품 중"))}),
        ("L", "외부 결품 상태가 '단종 예정'인 품목 가운데 가용 재고가 안전재고 이상인 품목은 몇 개야? (최종 답: 숫자)", X,
         {"kind": "number", "value": sum(1 for x in f if x["label"] == "단종 예정" and not x["low"])}),
        ("L", "전체 품목 가운데 외부 결품 기록(포장 단위 NDC 기준)이 10건 이상인 품목은 몇 개야? (최종 답: 숫자)", X,
         {"kind": "number", "value": sum(1 for n in recs.values() if n >= 10)}),
        ("L", "전체 품목의 외부 결품 기록(포장 단위 NDC 기준) 건수를 모두 더하면 몇 건이야? (최종 답: 숫자)", X,
         {"kind": "number", "value": sum(recs.values())}),
        ("L", "전체 품목 가운데 외부 결품 기록(포장 단위 NDC 기준) 건수가 두 번째로 많은 품목의 SKU와 그 건수는? (최종 답: SKU, 숫자)", X,
         {"kind": "sku_number", "value": {"skus": [ranked[1][1]], "number": ranked[1][0]}}),
        ("L", "공급사별로 외부 결품 상태가 '결품 중'인 품목 수를 셌을 때 가장 많은 공급사는 몇 개야? (최종 답: 숫자)", X,
         {"kind": "number", "value": top_sup[0]}),
    ]
    out, n = [], {}
    for t, text, tools, gold in items:
        n[t] = n.get(t, 0) + 1
        if gold["kind"] in ("set",) and not gold["value"]:
            raise ValueError(f"{t}{n[t]:02d} 정답 집합이 비었다")
        out.append({"id": f"{t}{n[t]:02d}", "type": t, "question": text, "expected_tools": tools, "gold": gold})
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--pilot2", action="store_true")
    g.add_argument("--main", action="store_true", help="본 평가 30문항(eval/questions_v3.jsonl)")
    a = ap.parse_args()
    out = PILOT_OUT if a.pilot else PILOT2_OUT if a.pilot2 else MAIN_OUT
    with psycopg.connect(config.ADMIN_DSN) as conn:
        items = pilot(conn) if a.pilot else pilot2(conn) if a.pilot2 else main_set(conn)
    out.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in items), encoding="utf-8")
    print(f"{len(items)}문항 저장: {out.relative_to(config.ROOT)}")
    for q in items:
        print(q["id"], q["type"], json.dumps(q["gold"]["value"], ensure_ascii=False)[:100])


if __name__ == "__main__":
    main()
