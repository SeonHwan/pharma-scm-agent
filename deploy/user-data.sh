#!/bin/bash
# EC2 첫 부팅 때 한 번 실행된다(cloud-init). Docker와 compose 플러그인을 설치하고,
# 3시간 뒤 스스로 종료한다. 인스턴스 시작 시 --instance-initiated-shutdown-behavior terminate 로 만들면
# 종료가 곧 삭제가 되어, 철거를 잊어도 비용이 무한정 늘지 않는다.
set -eux
# 안전장치를 가장 먼저 건다: 아래 설치가 실패해 스크립트가 중단돼도 3시간 뒤에는 종료(=삭제)된다.
shutdown -h +180
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user

ARCH=$(uname -m)   # aarch64(t4g) 또는 x86_64
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-${ARCH}" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

