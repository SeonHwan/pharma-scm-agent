"""결정적 합성 데이터: 공급사, SKU 선정, 재고 로트, 발주.

모든 난수는 문자열 시드의 random.Random으로만 만든다(같은 입력 → 같은 바이트).
경계 사례(안전재고 정확히 같음/1 모자람/0, 유통기한 +29/+30/+31일 등)를 의도적으로 심는다.
"""

import random
from collections import defaultdict
from datetime import timedelta

from . import config
from typing import Any

WAREHOUSES = ["WH-INC", "WH-BUS", "WH-DAE"]

_SUPPLIERS = [
    ("한빛제약공급", "KR"), ("Aster Pharma Supply", "US"), ("Nordic MedLogistics", "DK"),
    ("대성메디칼", "KR"), ("Rhein Wirkstoff GmbH", "DE"), ("Sakura Yakuhin", "JP"),
    ("Cobalt Generics", "IN"), ("Meridian Biologics", "US"), ("청명약품", "KR"),
    ("Alpina Pharma AG", "CH"), ("Baltic Drug Trade", "LT"), ("Orient Chem Source", "CN"),
]

# 결품 기록이 없는 성분(음성 사례). 스냅샷 성분명의 첫 단어와 겹치지 않는 것만 쓴다.
_NO_RECORD = [
    ("Atorvastatin Calcium Tablet", "Tablet", "Cardiovascular"),
    ("Amlodipine Besylate Tablet", "Tablet", "Cardiovascular"),
    ("Omeprazole Delayed-Release Capsule", "Capsule", "Gastroenterology"),
    ("Levothyroxine Sodium Tablet", "Tablet", "Endocrinology"),
    ("Simvastatin Tablet", "Tablet", "Cardiovascular"),
    ("Losartan Potassium Tablet", "Tablet", "Cardiovascular"),
    ("Sertraline Hydrochloride Tablet", "Tablet", "Psychiatry"),
    ("Gabapentin Capsule", "Capsule", "Neurology"),
    ("Pantoprazole Sodium Delayed-Release Tablet", "Tablet", "Gastroenterology"),
    ("Escitalopram Tablet", "Tablet", "Psychiatry"),
]


def rng(name):
    return random.Random(f"{config.SEED}:{name}")


def suppliers():
    r = rng("suppliers")
    rows = []
    for i, (name, country) in enumerate(_SUPPLIERS, 1):
        mean = r.randint(10, 60)
        rows.append((f"SUP-{i:02d}", name, country, mean, max(2, mean // 5)))
    return rows


def select_skus(records):
    """openFDA 성분명에서 층화 추출 + 결품 기록 없는 성분을 더해 SKU 목록을 만든다."""
    by_name = defaultdict(list)
    for rec in records:
        by_name[rec["generic_name"]].append(rec)
    groups = {"resolved": [], "both": [], "current": [], "tbd": []}
    for name in sorted(by_name):
        st = {x["status"] for x in by_name[name]}
        if "Resolved" in st:
            groups["resolved"].append(name)
        elif st == {"Current", "To Be Discontinued"}:
            groups["both"].append(name)
        elif st == {"Current"}:
            groups["current"].append(name)
        else:
            groups["tbd"].append(name)
    r = rng("select_skus")
    quota = {"resolved": 5, "both": 6, "current": 40, "tbd": 29}
    assert sum(quota.values()) == config.N_SKU_SHORTAGE
    names = []
    for g, n in quota.items():
        names += r.sample(groups[g], n)
    items = []
    for name in names:
        first = by_name[name][0]
        items.append((name, first.get("dosage_form"),
                      "; ".join(first.get("therapeutic_category") or []) or None))
    assert len(_NO_RECORD) == config.N_SKU_NO_RECORD
    firsts = {n.split()[0].lower() for n in by_name}
    for name, form, cat in _NO_RECORD:
        assert name.split()[0].lower() not in firsts, f"{name}: 스냅샷에 비슷한 성분이 있다"
        items.append((name, form, cat))
    r.shuffle(items)  # SKU 번호가 결품 여부를 드러내지 않게 한다
    return [(f"SKU-{i:03d}",) + it for i, it in enumerate(items, 1)]


def monthly_demand(sales_rows):
    """SKU별 최근 6개월(182일) 월평균 주문 수량."""
    start = config.AS_OF - timedelta(days=182)
    tot = defaultdict(int)
    for t in sales_rows:
        if t[3] >= start:
            tot[t[2]] += t[4]
    return {sku: q / 6 for sku, q in tot.items()}


def products(sku_items, demand):
    r = rng("products")
    sup_ids = [s[0] for s in suppliers()]
    rows = []
    for sku, name, form, cat in sku_items:
        base = demand.get(sku, 0)
        safety = max(500, round(base * r.uniform(0.8, 1.5) / 100) * 100)
        cold = (form == "Injection" and r.random() < 0.4) or r.random() < 0.05
        rows.append((sku, name, form, cat, "냉장" if cold else "상온", safety, r.choice(sup_ids)))
    return rows


def _split(r, total, n):
    w = [r.random() + 0.2 for _ in range(n)]
    parts = [max(1, int(total * x / sum(w))) for x in w]
    return parts


def lots(product_rows):
    """SKU당 1~4개 로트 + 경계 사례. 반환: [(lot_no, sku, qty, expiry, wh, status, received)]"""
    r = rng("lots")
    per_sku = {}
    for sku, _n, _f, _c, _s, safety, _sup in product_rows:
        n = r.randint(1, 4)
        total = int(safety * r.uniform(0.4, 2.4))
        per_sku[sku] = [
            dict(qty=q, expiry=config.AS_OF + timedelta(days=r.randint(20, 540)),
                 wh=r.choice(WAREHOUSES), status="quarantine" if r.random() < 0.05 else "available",
                 received=config.AS_OF - timedelta(days=r.randint(10, 300)))
            for q in _split(r, total, n)
        ]
    safety_of = {p[0]: p[5] for p in product_rows}
    pool = [p[0] for p in product_rows]
    r.shuffle(pool)

    def far(qty):
        return dict(qty=qty, expiry=config.AS_OF + timedelta(days=400), wh=r.choice(WAREHOUSES),
                    status="available", received=config.AS_OF - timedelta(days=30))

    for _ in range(3):   # 안전재고와 정확히 같다(미달 아님)
        s = pool.pop()
        per_sku[s] = [far(safety_of[s])]
    for _ in range(3):   # 1 모자란다(미달)
        s = pool.pop()
        per_sku[s] = [far(safety_of[s] - 1)]
    for _ in range(3):   # 재고 0
        s = pool.pop()
        per_sku[s] = [dict(far(0))]
    # 유통기한 경계: 기준일 +0/+29/+30/+31/+60/+90/+91일 로트를 추가
    for days in (0, 29, 30, 31, 60, 90, 91):
        s = pool.pop()
        e = far(300)
        e["expiry"] = config.AS_OF + timedelta(days=days)
        per_sku[s].append(e)
    for days in (-1, -30):   # 이미 만료(재고 수량은 남아 있으나 가용 아님)
        s = pool.pop()
        e = far(500)
        e["expiry"] = config.AS_OF + timedelta(days=days)
        per_sku[s].append(e)
    for _ in range(4):   # 격리 로트
        s = pool.pop()
        e = far(800)
        e["status"] = "quarantine"
        per_sku[s].append(e)
    out: list[tuple[Any, ...]] = []
    for sku in sorted(per_sku):
        for i, lot in enumerate(per_sku[sku], 1):
            out.append((f"LOT-{sku[-3:]}-{i:02d}", sku, lot["qty"], lot["expiry"], lot["wh"],
                        lot["status"], lot["received"]))
    return out


def purchase_orders(product_rows):
    r = rng("purchase_orders")
    sup = {s[0]: s for s in suppliers()}
    raw = []

    def add(sku, supplier_id, order_date, lead_expected, actual, qty):
        mean = sup[supplier_id][3]
        raw.append((order_date, sku, supplier_id,
                    order_date + timedelta(days=lead_expected if lead_expected else mean),
                    actual, qty))

    for sku, _n, _f, _c, _s, safety, supplier_id in product_rows:
        _, _, _, mean, sd = sup[supplier_id]
        for _ in range(r.randint(8, 16)):
            od = config.AS_OF - timedelta(days=r.randint(0, 1080))
            lead = max(3, round(r.gauss(mean, sd)))
            qty = max(100, round(safety * r.uniform(0.5, 1.5) / 100) * 100)
            add(sku, supplier_id, od, None, lead, qty)
    # 기한 경과 미입고(expected < 기준일) / 기한이 기준일과 같은 미입고(경과 아님)
    skus = [p[0] for p in product_rows]
    r.shuffle(skus)
    pmap = {p[0]: p for p in product_rows}
    for i, sku in enumerate(skus[:14]):
        supplier_id = pmap[sku][6]
        mean = sup[supplier_id][3]
        late_by = r.randint(5, 30) if i < 12 else 0
        od = config.AS_OF - timedelta(days=mean + late_by)
        add(sku, supplier_id, od, None, 10**6, max(100, pmap[sku][5]))  # 입고 안 됨
    raw.sort(key=lambda t: (t[0], t[1], t[5]))
    out: list[tuple[Any, ...]] = []
    for i, (od, sku, supplier_id, expected, actual, qty) in enumerate(raw, 1):
        received = od + timedelta(days=actual)
        if received <= config.AS_OF:
            out.append((f"PO-{i:05d}", sku, supplier_id, od, expected, received, qty, "received"))
        else:
            out.append((f"PO-{i:05d}", sku, supplier_id, od, expected, None, qty, "open"))
    return out
