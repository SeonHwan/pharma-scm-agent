"""전체 데이터를 처음부터 다시 만든다(멱등). 실행: uv run python -m pharma_scm.build"""


import psycopg

from . import config, load_dataco, load_openfda, sop, synth

_TABLES = ["suppliers", "products", "sales_orders", "inventory_lots", "purchase_orders",
           "shortage_events", "sop_sections"]


def checksums(conn):
    out = {}
    with conn.cursor() as cur:
        for t in _TABLES:
            cur.execute(f"SELECT count(*), md5(coalesce(string_agg(x::text, E'\\n' "
                        f"ORDER BY x::text), '')) FROM {t} x")
            out[t] = cur.fetchone()
    return out


def main():
    schema = (config.ROOT / "src" / "pharma_scm" / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(config.ADMIN_DSN) as conn:
        conn.execute(schema)
        records = load_openfda.load(conn)
        sku_items = synth.select_skus(records)
        skus = [s[0] for s in sku_items]
        dc_rows = load_dataco.read_rows()
        sales = load_dataco.sales_rows(dc_rows, load_dataco.sku_map(dc_rows, skus))
        prods = synth.products(sku_items, synth.monthly_demand(sales))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO suppliers VALUES (%s,%s,%s,%s,%s)", synth.suppliers())
            cur.executemany("INSERT INTO products VALUES (%s,%s,%s,%s,%s,%s,%s)", prods)
        load_dataco.load(conn, sales)
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO inventory_lots VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            synth.lots(prods))
            cur.executemany("INSERT INTO purchase_orders VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            synth.purchase_orders(prods))
        sop.load(conn)
        conn.execute("INSERT INTO meta VALUES ('as_of', %s), ('shortage_snapshot', %s)",
                     (config.AS_OF.isoformat(), config.SHORTAGE_SNAPSHOT))
        conn.execute("GRANT SELECT ON products, sales_orders, suppliers, purchase_orders, "
                     "inventory_lots TO pharma_ro")
        conn.execute("GRANT SELECT ON shortage_events, sop_sections TO pharma_ext")
        sums = checksums(conn)
    for t, (n, h) in sums.items():
        print(f"{t:16s} {n:>7d}  {h}")


if __name__ == "__main__":
    main()
