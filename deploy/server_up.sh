#!/usr/bin/env bash
# 소스를 올리고 서버에서 DB 복원·API 기동. 인자: 서버 IP. (ssh/scp만, 이 PC에 AWS CLI 불필요)
# 비밀은 올리지 않음: 서버가 자기 IAM 역할로 SSM에서 읽음(deploy/fetch_secrets.sh, 6단계).
# 사전: /pharma/api_key, /pharma/anthropic_api_key 파라미터 (deploy/terraform/README.md)
set -euo pipefail
IP=${1:?서버 IP}; K=~/.ssh/pharma-p5.pem; O="-i $K -o StrictHostKeyChecking=accept-new"
git archive --format=tar.gz -o /tmp/pharma-src.tgz HEAD
scp $O /tmp/pharma-src.tgz ec2-user@"$IP":~/
ssh $O ec2-user@"$IP" 'bash -s' <<'R'
set -e
cloud-init status --wait; docker compose version
mkdir -p app && tar -xzf pharma-src.tgz -C app && cd app
deploy/fetch_secrets.sh
DC="docker compose -f deploy/compose.deploy.yaml --env-file deploy/deploy.env"
$DC up -d db; sleep 10
deploy/restore_db.sh deploy/pharma.sql.gz </dev/null
$DC up -d --build api; sleep 15
$DC ps; curl -s localhost:8000/ready
R
