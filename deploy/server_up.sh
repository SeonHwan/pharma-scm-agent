#!/usr/bin/env bash
# 7장: 소스·비밀을 올리고 서버에서 DB 복원·API 기동. 인자: 서버 IP. (AWS CLI 불필요, ssh/scp만)
set -euo pipefail
IP=${1:?서버 IP}; K=~/.ssh/pharma-p5.pem; O="-i $K -o StrictHostKeyChecking=accept-new"
git archive --format=tar.gz -o /tmp/pharma-src.tgz HEAD
scp $O /tmp/pharma-src.tgz deploy/deploy.env ec2-user@"$IP":~/
ssh $O ec2-user@"$IP" 'bash -s' <<'R'
set -e
cloud-init status --wait; docker compose version
mkdir -p app && tar -xzf pharma-src.tgz -C app && mv deploy.env app/deploy/ && cd app
DC="docker compose -f deploy/compose.deploy.yaml --env-file deploy/deploy.env"
$DC up -d db; sleep 10
deploy/restore_db.sh deploy/pharma.sql.gz </dev/null
$DC up -d --build api; sleep 15
$DC ps; curl -s localhost:8000/ready
R
