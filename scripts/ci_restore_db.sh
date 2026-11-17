#!/usr/bin/env bash
# CI(와 로컬 재현)용: 떠 있는 Postgres에 읽기 전용 역할을 만들고 deploy/pharma.sql.gz를 복원한다.
# deploy/restore_db.sh는 docker compose exec를 쓰므로 서비스 컨테이너에는 못 쓴다 — 같은 3단계를 psql로 직접 한다.
# 환경: PGHOST(기본 localhost) PGPORT(기본 5433) PGPASSWORD(기본 local-dev-only). config.py의 기본 DSN과 맞춘다.
set -euo pipefail

cd "$(dirname "$0")/.."
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5433}" PGPASSWORD="${PGPASSWORD:-local-dev-only}"
psql_admin() { psql -v ON_ERROR_STOP=1 -q -U pharma_admin -d pharma "$@"; }

echo "1) 읽기 전용 역할 생성(덤프의 GRANT가 역할을 필요로 한다)"
psql_admin <<SQL
CREATE ROLE pharma_ro  LOGIN PASSWORD '${PGPASSWORD}';
CREATE ROLE pharma_ext LOGIN PASSWORD '${PGPASSWORD}';
SQL

echo "2) 덤프 복원"
gunzip -c deploy/pharma.sql.gz | psql_admin

echo "3) 역할 설정 적용(pg_dump는 역할별 설정을 담지 않는다)"
psql_admin <<'SQL'
ALTER ROLE pharma_ro  SET default_transaction_read_only = on;
ALTER ROLE pharma_ro  SET statement_timeout = '5s';
ALTER ROLE pharma_ext SET default_transaction_read_only = on;
ALTER ROLE pharma_ext SET statement_timeout = '5s';
SQL

echo "4) 행 수 확인"
actual="$(psql_admin -At -F: -c "SELECT 'products', count(*) FROM products UNION ALL SELECT 'sales_orders', count(*) FROM sales_orders UNION ALL SELECT 'inventory_lots', count(*) FROM inventory_lots UNION ALL SELECT 'shortage_events', count(*) FROM shortage_events UNION ALL SELECT 'sop_sections', count(*) FROM sop_sections")"
expected="products:90
sales_orders:180519
inventory_lots:228
shortage_events:1622
sop_sections:30"
echo "$actual"
[ "$actual" = "$expected" ] || { echo "행 수가 기대값과 다르다" >&2; exit 1; }
echo "완료"
