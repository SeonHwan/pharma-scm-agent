"""DataCo 주문·배송 성과를 약품 SKU에 매핑해 sales_orders 행으로 만든다.

실제 약품 수요가 아니라 수요·배송 패턴의 대역(stand-in)이다.
"""

import csv
import io
import zipfile
from datetime import datetime, timedelta

from . import config

ZIP_NAME = "8gx2fvg2k6-5.zip"
CSV_NAME = "DataCoSupplyChainDataset.csv"


def read_rows():
    with zipfile.ZipFile(config.RAW_DIR / ZIP_NAME) as z, z.open(CSV_NAME) as raw:
        text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
        return list(csv.DictReader(text))


def sku_map(rows, skus):
    """DataCo Product Card Id를 오름차순으로 세워 SKU에 순환 배정한다."""
    pids = sorted({int(r["Product Card Id"]) for r in rows})
    return {pid: skus[i % len(skus)] for i, pid in enumerate(pids)}


def sales_rows(rows, mapping):
    shift = timedelta(days=config.DATE_SHIFT_DAYS)
    out = []
    for r in rows:
        d = datetime.strptime(r["order date (DateOrders)"], "%m/%d/%Y %H:%M").date() + shift
        out.append((
            int(r["Order Item Id"]),
            int(r["Order Id"]),
            mapping[int(r["Product Card Id"])],
            d,
            int(r["Order Item Quantity"]) * config.QUANTITY_SCALE,
            int(r["Days for shipping (real)"]),
            int(r["Days for shipment (scheduled)"]),
            r["Late_delivery_risk"] == "1",
            r["Delivery Status"],
            r["Order Status"],
            r["Market"],
        ))
    out.sort(key=lambda t: t[0])
    return out


def load(conn, rows_out):
    with conn.cursor() as cur, cur.copy(
        "COPY sales_orders (order_item_id, order_id, sku, order_date, quantity, "
        "days_shipping_real, days_shipping_scheduled, late_delivery, delivery_status, "
        "order_status, market) FROM STDIN"
    ) as cp:
        for t in rows_out:
            cp.write_row(t)
