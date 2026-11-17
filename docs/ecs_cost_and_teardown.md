# 7단계 ECS Fargate: 비용 추정과 철거 계획 (2026-11-16, 실행 전)

만들기 **전에** 적는 문서다. 요금은 이 PC에서 AWS 요금 페이지에 접속하지 못해(인증서 오류) 웹 검색 결과로만 확인했고, **서울(ap-northeast-2) 값은 대부분 미확인**이다. 맥북에서 AWS Pricing Calculator(서울 리전 선택)로 확인한 뒤 이 표를 고친다.

## 1. 만들 자원

| 자원 | 과금 방식 | 단가 | 근거 |
|---|---|---|---|
| Fargate 태스크 (0.5 vCPU, 1GB, amd64, 1개) | 켜 둔 시간(초 단위) | vCPU 약 $0.0506/h, 메모리 약 $0.0127/h → 태스크 약 $0.038/h | 한국어 AWS 블로그 글의 수치. 리전·시점 불명확, **미확인** |
| ALB (Application Load Balancer) | 시간당 고정 + LCU(처리량) | 미국 동부 기준 $0.0225/h + LCU $0.008/h. **서울 미확인** | 미국 값은 참고용. 서울은 더 비쌀 수 있음 |
| RDS PostgreSQL (`db.t4g.micro`, 단일 AZ) | 인스턴스 시간 + 디스크 GB-월 | 인스턴스 약 $0.025/h(월 $18.25), 디스크 gp3 약 $0.131/GB-월(20GB 월 $2.62) | RDS 생성 화면의 서울 리전 "예상 월 비용"(2026-11-17, 사용자 보고). 합계 월 $20.87 |
| 공인 IPv4 주소 | 시간당 | 개당 약 $0.005/h로 알고 있음(2024년부터 과금). **미확인** | ALB(서브넷 2개 = IP 2개)와 태스크(공인 IP 1개)에 붙음 |
| ECR 저장소 | 저장 용량(GB-월) | 이미지 약 0.5GB, 소액 | 단가 미확인 |
| CloudWatch Logs | 수집·저장 용량 | 로그가 적어 소액 | 단가 미확인 |
| SSM Parameter Store(표준) | 무료로 알고 있음 | 이미 6단계에서 사용 중 | 미확인 |

**NAT Gateway는 쓰지 않는다.** 태스크를 공용 서브넷에 두고 공인 IP를 붙여 ECR·SSM·Anthropic API에 나간다. 대신 보안 그룹으로 ALB에서 오는 트래픽만 받는다(트레이드오프: 태스크가 공인 IP를 가짐. 현업은 비공개 서브넷+NAT 또는 VPC 엔드포인트를 쓰는 경우가 많다).

## 2. 시간당 상한 추정 (미확인 값 포함, 넉넉하게)

| 항목 | 시간당 |
|---|---|
| Fargate 태스크 | $0.04 |
| ALB (서울이 비싸다고 가정) | $0.04 |
| RDS 인스턴스 | $0.03 |
| 공인 IPv4 3개 | $0.015 |
| 합계 | **약 $0.13/h** |

- 하루(24시간) 켜 두면 약 $3, 한 달이면 약 $95다. **깜빡 켜 두는 것이 가장 큰 위험**이다.
- 실습 한 번을 4시간으로 잡으면 약 $0.5다. RDS 디스크는 시간이 아닌 용량 과금이라 20GB 기준 월 $2~3 수준으로 추정한다(단가 미확인).
- 이 외에 `/ask` 시험 호출의 Anthropic API 비용이 있다. 3문항 기준 호출 약 5~6회, 입력 약 1.4만 토큰으로 추정한다(`docs/operations.md`의 3문항 확인 기록 기준). 실행 전에 다시 계산해 보여 준다.
- 비용은 신규 계정 무료 크레딧으로 충당한다. 정확한 사용액은 철거 후 Billing 화면에서 확인해 아래 "실측" 칸에 적는다.

## 3. 시작 전 점검 (맥북, 콘솔)
- [ ] AWS Budgets에 비용 알림이 있는지(없으면 월 $10 정도로 먼저 만든다)
- [ ] `export AWS_PROFILE=<이름>` 지정, `aws sts get-caller-identity`로 계정 확인
- [ ] 이전 배포 잔여물 없음: EC2 인스턴스, Elastic IP, 보안 그룹 확인
- [ ] 리전이 서울(ap-northeast-2)인지

## 4. 철거 순서와 확인 (콘솔로 만든 것은 직접 삭제한다)
의존 관계상 **바깥(서비스)부터 안쪽(DB)** 순으로 지운다.

1. ECS 서비스: 원하는 태스크 수를 0으로 바꾼 뒤 삭제
2. ALB 삭제 → 타깃 그룹 삭제
3. RDS 삭제: "최종 스냅샷 생성"은 끄고, "자동 백업 보존"도 함께 삭제한다. (스냅샷이 남으면 용량 과금이 계속됨)
4. ECR 저장소 삭제(이미지 포함)
5. CloudWatch **로그 그룹 삭제**: 다른 자원을 지워도 로그 그룹은 남는다
6. 보안 그룹 3개(ALB용, 태스크용, RDS용), RDS 서브넷 그룹 삭제: 연결된 자원이 먼저 사라져야 지워진다
7. IAM 역할(실행 역할)은 유지할지 삭제할지 정한다. 역할은 과금되지 않는다
8. SSM 파라미터는 유지(6단계에서 만든 것)

**철거 확인(맥북에서 직접 실행, 출력을 붙여 주면 기록한다)**
```
aws ecs list-clusters
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws rds describe-db-snapshots --query 'DBSnapshots[].DBSnapshotIdentifier'
aws ecr describe-repositories --query 'repositories[].repositoryName'
aws logs describe-log-groups --query 'logGroups[].logGroupName'
aws ec2 describe-addresses
aws ec2 describe-network-interfaces --query 'NetworkInterfaces[].Description'
```
모두 비어 있거나 이번에 만든 이름이 없어야 한다. 다음 날 Billing(Cost Explorer)에서 서비스별 비용이 더 늘지 않는지 한 번 더 본다.

## 5. 실측 (실행 후 채운다)
| 항목 | 값 |
|---|---|
| 자원을 켜 둔 총 시간 | 미기록 |
| Billing에서 확인한 사용액 | 미기록 |
| 위 추정과의 차이 | 미기록 |
