#!/usr/bin/env bash
# 9장: 철거와 확인(aws CLI 필요)
set -uo pipefail
source ~/.pharma-p5-ids; export AWS_PAGER=""
aws ec2 terminate-instances --instance-ids "$IID"
aws ec2 wait instance-terminated --instance-ids "$IID"
aws ec2 delete-security-group --group-id "$SG"
aws ec2 delete-key-pair --key-name pharma-p5
rm -f ~/.ssh/pharma-p5.pem
echo "--- 확인(모두 terminated/빈 값이어야 함)"
aws ec2 describe-instances --filters Name=tag:Project,Values=pharma-p5 --query 'Reservations[].Instances[].State.Name'
aws ec2 describe-volumes --filters Name=tag:Project,Values=pharma-p5 --query 'Volumes[].VolumeId'
aws ec2 describe-addresses --query 'Addresses[].PublicIp'
aws ec2 describe-security-groups --filters Name=group-name,Values=pharma-p5 --query 'SecurityGroups[].GroupId'
