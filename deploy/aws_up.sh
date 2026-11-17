#!/usr/bin/env bash
# 6장: AWS 리소스 생성. 사용: aws_up.sh [허용할 공인 IP, 생략하면 이 PC]. 철거용 값은 ~/.pharma-p5-ids에 저장.
set -euo pipefail
export AWS_REGION=${AWS_REGION:-ap-northeast-2} AWS_PAGER=""
MYIP=${1:-$(curl -s https://checkip.amazonaws.com)}
aws ec2 create-key-pair --key-name pharma-p5 --query KeyMaterial --output text > ~/.ssh/pharma-p5.pem
chmod 600 ~/.ssh/pharma-p5.pem
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 create-security-group --group-name pharma-p5 --description "pharma p5 temp" --vpc-id "$VPC" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$MYIP/32"
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 8000 --cidr "$MYIP/32"
AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 --query Parameter.Value --output text)
IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type t4g.small --key-name pharma-p5 \
  --security-group-ids "$SG" --instance-initiated-shutdown-behavior terminate \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp3,DeleteOnTermination=true}' \
  --user-data file://deploy/user-data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=pharma-p5}]' 'ResourceType=volume,Tags=[{Key=Project,Value=pharma-p5}]' \
  --query 'Instances[0].InstanceId' --output text)
printf 'export AWS_REGION=%s\nIID=%s\nSG=%s\n' "$AWS_REGION" "$IID" "$SG" > ~/.pharma-p5-ids
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "IP=$IP" >> ~/.pharma-p5-ids
echo "서버 IP: $IP (3시간 뒤 자동 종료). 다음: deploy/server_up.sh $IP"
