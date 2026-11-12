#!/usr/bin/env bash
# 서버에서 실행: deploy.env를 SSM Parameter Store에서 읽어 만든다(서버의 IAM 역할 사용, 키 복사 없음).
# DB 비밀번호는 이 서버의 컨테이너끼리만 쓰므로 서버에서 새로 만든다.
# 사용:  deploy/fetch_secrets.sh [출력 파일, 기본 deploy/deploy.env]
set -euo pipefail
OUT="${1:-$(dirname "$0")/deploy.env}"
REGION="${AWS_REGION:-ap-northeast-2}"
get() { aws ssm get-parameter --name "$1" --with-decryption --query Parameter.Value --output text --region "$REGION"; }

# 먼저 변수로 읽는다: echo 안의 $(...)는 get이 실패해도 파일에 빈 값이 써진다(set -e가 안 걸린다).
API_KEY=$(get /pharma/api_key)
ANTHROPIC_KEY=$(get /pharma/anthropic_api_key)
[ -n "$API_KEY" ] && [ -n "$ANTHROPIC_KEY" ] || { echo "SSM 값이 비어 있다" >&2; exit 1; }

umask 077
cat > "$OUT" <<ENV
DB_ADMIN_PASSWORD=$(openssl rand -hex 16)
DB_RO_PASSWORD=$(openssl rand -hex 16)
DB_EXT_PASSWORD=$(openssl rand -hex 16)
PHARMA_API_KEY=$API_KEY
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
API_PORT=8000
ENV
echo "비밀 5개를 SSM에서 읽어 $OUT 을 만들었다(값은 출력하지 않는다)"
