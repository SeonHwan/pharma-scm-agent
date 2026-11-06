#!/usr/bin/env bash
# DB 컨테이너가 떠 있는 상태에서 읽기 전용 역할을 만들고 덤프를 복원한다(처음 한 번만 실행).
# 사용:  deploy/restore_db.sh pharma.sql.gz        (저장소 루트 어디서 불러도 된다)
# 환경: deploy/deploy.env 의 DB_RO_PASSWORD, DB_EXT_PASSWORD 를 쓴다. 다른 파일은 ENV_FILE=경로 로 지정.
set -euo pipefail

DUMP="$(cd "$(dirname "${1:?덤프 파일 경로(pharma.sql.gz)를 인자로 주세요}")" && pwd)/$(basename "$1")"
cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-deploy.env}"
[ -f "$DUMP" ] || { echo "덤프 파일이 없다: $DUMP" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "환경 파일이 없다: $ENV_FILE (deploy.env.example을 복사해 채운다)" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a

dc() { docker compose -f compose.deploy.yaml --env-file "$ENV_FILE" "$@"; }
psql_admin() { dc exec -T db psql -v ON_ERROR_STOP=1 -q -U pharma_admin -d pharma "$@"; }

echo "1) 읽기 전용 역할 생성(덤프의 GRANT가 역할을 필요로 한다)"
psql_admin <<SQL
CREATE ROLE pharma_ro  LOGIN PASSWORD '${DB_RO_PASSWORD}';
CREATE ROLE pharma_ext LOGIN PASSWORD '${DB_EXT_PASSWORD}';
SQL

echo "2) 덤프 복원"
gunzip -c "$DUMP" | psql_admin

echo "3) 역할 설정 적용(pg_dump는 역할별 설정을 담지 않는다)"
psql_admin <<'SQL'
ALTER ROLE pharma_ro  SET default_transaction_read_only = on;
ALTER ROLE pharma_ro  SET statement_timeout = '5s';
ALTER ROLE pharma_ext SET default_transaction_read_only = on;
ALTER ROLE pharma_ext SET statement_timeout = '5s';
SQL

echo "4) 확인: 행 수(기대: products 90, sales_orders 180519, inventory_lots 228, shortage_events 1622, sop_sections 30)"
psql_admin -At -c "SELECT 'products', count(*) FROM products UNION ALL SELECT 'sales_orders', count(*) FROM sales_orders UNION ALL SELECT 'inventory_lots', count(*) FROM inventory_lots UNION ALL SELECT 'shortage_events', count(*) FROM shortage_events UNION ALL SELECT 'sop_sections', count(*) FROM sop_sections"
echo "완료"
