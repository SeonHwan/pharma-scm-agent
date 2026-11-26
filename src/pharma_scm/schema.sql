DROP TABLE IF EXISTS sop_sections, shortage_events, purchase_orders, inventory_lots,
    sales_orders, products, suppliers, meta CASCADE;

CREATE TABLE meta (key text PRIMARY KEY, value text NOT NULL);

CREATE TABLE suppliers (
    supplier_id text PRIMARY KEY,
    name text NOT NULL,
    country text NOT NULL,
    lead_time_days_mean int NOT NULL,
    lead_time_days_sd int NOT NULL
);

CREATE TABLE products (
    sku text PRIMARY KEY,
    generic_name text NOT NULL,
    dosage_form text,
    therapeutic_category text,
    storage_condition text NOT NULL,      -- '상온' | '냉장'
    safety_stock int NOT NULL,
    supplier_id text NOT NULL REFERENCES suppliers
);

CREATE TABLE sales_orders (
    order_item_id bigint PRIMARY KEY,
    order_id bigint NOT NULL,
    sku text NOT NULL REFERENCES products,
    order_date date NOT NULL,
    quantity int NOT NULL,
    days_shipping_real int NOT NULL,
    days_shipping_scheduled int NOT NULL,
    late_delivery boolean NOT NULL,
    delivery_status text NOT NULL,
    order_status text NOT NULL,
    market text NOT NULL
);

CREATE TABLE inventory_lots (
    lot_no text PRIMARY KEY,
    sku text NOT NULL REFERENCES products,
    quantity int NOT NULL,
    expiry_date date NOT NULL,
    warehouse text NOT NULL,              -- 'WH-INC' | 'WH-BUS' | 'WH-DAE'
    lot_status text NOT NULL,             -- 'available' | 'quarantine'
    received_date date NOT NULL
);

CREATE TABLE purchase_orders (
    po_id text PRIMARY KEY,
    sku text NOT NULL REFERENCES products,
    supplier_id text NOT NULL REFERENCES suppliers,
    order_date date NOT NULL,
    expected_date date NOT NULL,
    received_date date,                   -- NULL이면 미입고
    quantity int NOT NULL,
    status text NOT NULL                  -- 'received' | 'open'
);

-- openFDA 결품 스냅샷 원본. query_db 계정에는 권한을 주지 않는다.
CREATE TABLE shortage_events (
    package_ndc text NOT NULL,
    generic_name text NOT NULL,
    status text NOT NULL,                 -- 'Current' | 'To Be Discontinued' | 'Resolved'
    dosage_form text,
    presentation text,
    company_name text,
    therapeutic_category text,
    initial_posting_date date,
    update_date date,
    discontinued_date date,
    update_type text,
    availability text,
    shortage_reason text,
    resolved_note text,
    related_info text
);
CREATE INDEX ON shortage_events (generic_name);

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pharma_ro') THEN
        CREATE ROLE pharma_ro LOGIN PASSWORD 'local-dev-only';
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pharma_ext') THEN
        CREATE ROLE pharma_ext LOGIN PASSWORD 'local-dev-only';
    END IF;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pharma_ro, pharma_ext;
GRANT SELECT ON products, sales_orders, suppliers, purchase_orders, inventory_lots TO pharma_ro;
ALTER ROLE pharma_ro SET default_transaction_read_only = on;
ALTER ROLE pharma_ro SET statement_timeout = '5s';
-- get_shortage 전용 계정: 결품 스냅샷만 읽는다(규정 문서는 DB가 아니라 sop/ 파일과 검색 색인에 있다).
ALTER ROLE pharma_ext SET default_transaction_read_only = on;
ALTER ROLE pharma_ext SET statement_timeout = '5s';
