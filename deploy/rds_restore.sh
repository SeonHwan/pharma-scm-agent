#!/usr/bin/env bash
# RDS(관리형 PostgreSQL)에 읽기 전용 역할을 만들고 덤프를 복원. 일회성 ECS 태스크 안에서 실행(처음 한 번만).
# 환경: PGHOST, PGUSER, PGPASSWORD, PGDATABASE(psql이 직접 읽는 표준 변수), DB_RO_PASSWORD, DB_EXT_PASSWORD
# 사용:  rds_restore.sh [덤프 파일, 기본 /pharma.sql.gz]
set -euo pipefail

DUMP="${1:-/pharma.sql.gz}"
for v in PGHOST PGUSER PGPASSWORD PGDATABASE DB_RO_PASSWORD DB_EXT_PASSWORD; do
  [ -n "${!v:-}" ] || { echo "환경변수 $v 가 비어 있다" >&2; exit 1; }
done
[ -f "$DUMP" ] || { echo "덤프 파일이 없다: $DUMP" >&2; exit 1; }

psql_admin() { psql -v ON_ERROR_STOP=1 -q "$@"; }

echo "0) 접속 확인"
psql_admin -At -c "SELECT current_user, current_database()"

echo "1) 이미 복원됐는지 확인(중복 복원을 막는다)"
if [ "$(psql_admin -At -c "SELECT to_regclass('public.products') IS NOT NULL")" = "t" ]; then
  echo "products 테이블이 이미 있다. 복원을 중단한다(처음부터 다시 하려면 DB를 비운 뒤 실행)" >&2
  exit 1
fi

echo "2) 읽기 전용 역할 생성(덤프의 GRANT가 역할을 필요로 한다)"
psql_admin -v ro_pw="$DB_RO_PASSWORD" -v ext_pw="$DB_EXT_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE pharma_ro LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pharma_ro') \gexec
SELECT 'CREATE ROLE pharma_ext LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pharma_ext') \gexec
ALTER ROLE pharma_ro PASSWORD :'ro_pw';
ALTER ROLE pharma_ext PASSWORD :'ext_pw';
SQL

echo "3) 덤프 복원"
gunzip -c "$DUMP" | psql_admin

echo "4) 역할 설정 적용(pg_dump는 역할별 설정을 담지 않는다)"
psql_admin <<'SQL'
ALTER ROLE pharma_ro  SET default_transaction_read_only = on;
ALTER ROLE pharma_ro  SET statement_timeout = '5s';
ALTER ROLE pharma_ext SET default_transaction_read_only = on;
ALTER ROLE pharma_ext SET statement_timeout = '5s';
SQL

echo "5) 확인: 행 수(기대: products 90, sales_orders 180519, inventory_lots 228, shortage_events 1622)"
psql_admin -At -c "SELECT 'products', count(*) FROM products UNION ALL SELECT 'sales_orders', count(*) FROM sales_orders UNION ALL SELECT 'inventory_lots', count(*) FROM inventory_lots UNION ALL SELECT 'shortage_events', count(*) FROM shortage_events"
echo "완료"
