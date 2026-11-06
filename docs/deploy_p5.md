# P5 배포 가이드 (맥북에서 실행)

목표: **AWS EC2 한 대에 올려서 외부에서 호출해 보고, 바로 내린다.** 상시 운영이 아니다.
이 PC는 인증서 문제로 `aws` 호출이 안 되어 맥북에서 실행한다. 이 문서는 맥북에서 위에서 아래로 따라 하는 체크리스트다.

## 0. 한눈에

| 항목 | 내용 |
|---|---|
| 구성 | EC2 한 대(Amazon Linux 2023, `t4g.small`) 안에 Docker로 Postgres와 API 컨테이너 |
| 공개 범위 | 보안 그룹으로 **내 공인 IP 하나**(`/32`)에서만 22(SSH), 8000(API) 접근. DB 포트는 열지 않음 |
| 소요 시간 | 약 1~1.5시간(처음이라면) |
| 예상 비용 | 3시간 이내면 **수십 센트 이하**로 추정(아래 "비용" 참고). 실제 금액은 철거 다음 날 청구 화면에서 확인 |
| 안전장치 | ① 비용 알림 ② 3시간 뒤 서버가 스스로 종료·삭제 ③ 철거 체크리스트 ④ 배포 전용 키(끝나면 폐기) |
| 중단 기준 | 한 단계에서 30분 넘게 막히거나 비용 알림이 오면 **즉시 9장(철거)으로** |

### 비용(추정, 요금 페이지에서 확인할 것)
- `t4g.small` 온디맨드: 시간당 대략 0.02달러 안팎
- 공인 IPv4 주소: 시간당 대략 0.005달러
- EBS gp3 16GB: 월 1~2달러 수준이라 몇 시간이면 센트 단위
- 모델 호출: `/ask` 1건에 소액(앞선 측정에서 입력 약 5k·출력 약 0.2k 토큰)
- 리전과 시점에 따라 다르고 계정의 무료 크레딧 여부도 다르다. **위 숫자는 이 문서를 쓴 시점의 기억에 기반한 추정**이다.

## 1. 검증 상태 (2026-11-06 기준, 이 PC에서)

**이 PC에서 예행연습으로 확인한 것** (AWS와 무관한 부분)
- `deploy/compose.deploy.yaml`로 새 Postgres 컨테이너를 띄우고 `deploy/restore_db.sh`로 덤프를 복원: 행 수가 기대와 일치(products 90, sales_orders 180,519, inventory_lots 228, shortage_events 1,622, sop_sections 30)
- 복원 뒤 읽기 전용 역할 동작: `pharma_ro`의 `DELETE`는 거부되고, 허용 밖 테이블(`shortage_events`)은 접근 거부
- 같은 compose로 API 컨테이너를 빌드·실행: `/health` 200, `/ready` 200(DB 2개·모델 키 ok), 키 없이 `/ask` 401, 실제 `/ask`(A001) 정답(189779)
- 컨테이너는 비루트(`app`) 사용자로 실행, DB 포트는 호스트에 공개되지 않음

**이 PC에서 확인하지 못한 것** (맥북에서 처음 실행할 때 확인된다)
- `aws` 명령 전부(키 쌍, 보안 그룹, 인스턴스 생성, 철거), SSH/SCP, EC2 user-data 실행
- Amazon Linux 2023 `arm64`에서의 Docker·compose 설치(compose 바이너리 URL의 버전 `v2.32.4` 포함)와 이미지 빌드(예행연습은 x86_64에서 했다)
- 아래 `aws` 명령의 옵션 이름과 출력 형식은 일반적인 사용법에 따라 썼고 실제로 실행해 보지 못했다. **오류가 나면 출력을 그대로 알려 달라.**

## 2. 준비물 (맥북)

- AWS 계정(루트 계정이 아닌 **IAM 사용자 또는 IAM Identity Center 사용자**로 쓰고 MFA 켜기)
- `aws` CLI v2: `brew install awscli` 후 `aws configure`(또는 `aws configure sso`), 확인: `aws sts get-caller-identity`
- `git`, `ssh`, `scp`, `curl`, `openssl` (macOS 기본 포함). **Docker는 맥북에 필요 없다**(서버에서 빌드)
- GitHub 저장소 접근(private): `gh auth login` 또는 SSH 키
- Anthropic Console 접근(배포 전용 키를 새로 만들기 위해)
- 이 PC에서 만든 데이터 파일 `deploy/pharma.sql.gz`(1.4MB). 5장 참고

```bash
git clone https://github.com/SeonHwan/pharma-scm-agent.git
cd pharma-scm-agent
```
이후 명령은 모두 이 저장소 루트에서 실행한다.

## 3. 비용 알림부터 (AWS 콘솔)

1. Billing and Cost Management → **Budgets** → Create budget → "Monthly cost budget"
2. 금액: 원하는 한도(예: 5달러). 알림: **실제 지출 50%·100%**, **예측 지출 100%**, 받을 이메일 입력
3. Billing preferences에서 결제 알림 이메일을 켠다

> **중요**: Budgets는 **알림**이지 차단이 아니다. 청구 데이터가 반영되기까지 몇 시간에서 하루가 걸려 알림도 늦을 수 있다. 진짜 안전장치는 서버의 **3시간 자동 종료**와 **철거**다.

## 4. 배포 전용 비밀 만들기

```bash
cp deploy/deploy.env.example deploy/deploy.env
chmod 600 deploy/deploy.env
```
`deploy/deploy.env`를 편집기로 열어 빈 값을 채운다.
- `DB_ADMIN_PASSWORD`, `DB_RO_PASSWORD`, `DB_EXT_PASSWORD`: 각각 `openssl rand -hex 16` 결과
- `PHARMA_API_KEY`: `openssl rand -hex 24` 결과 (**이 PC의 `.env` 키와 다른, 이번 배포 전용 키**)
- `ANTHROPIC_API_KEY`: Anthropic Console에서 **이번 배포 전용 키를 새로 만들어** 넣는다. 가능하면 지출 한도를 낮게 두고, 끝나면 삭제한다. 평소 쓰는 키를 쓰지 않는다.

`deploy.env`는 `.gitignore`에 있어 커밋되지 않는다. 셸 기록에 키가 남지 않도록 **키는 명령줄에 직접 치지 말고 편집기로 붙여 넣는다.**

## 5. 데이터 파일 옮기기

DB 내용(합성·변환 데이터)은 저장소에 없고 이 PC의 Postgres에만 있다. 덤프(1.4MB, gzip)를 이미 만들어 두었다.

- 위치: 이 PC의 `~/pharma-scm-agent/deploy/pharma.sql.gz` (`.gitignore`에 있어 저장소에 올라가지 않는다)
- 맥북으로 옮기기: 본인에게 메일·메신저·클라우드 드라이브·USB 등 편한 방법으로 보내 맥북의 `pharma-scm-agent/deploy/` 폴더에 둔다. **저장소(GitHub)에 올리지 않는다.**
- 다시 만들어야 하면(이 PC에서, DB 컨테이너가 떠 있을 때):
  ```bash
  docker compose exec -T db pg_dump -U pharma_admin -d pharma --no-owner | gzip > deploy/pharma.sql.gz
  ```

## 6. AWS 리소스 만들기 (맥북)

```bash
export AWS_REGION=ap-northeast-2        # 서울. 다른 리전도 가능
export AWS_PAGER=""
MYIP=$(curl -s https://checkip.amazonaws.com)

# 키 쌍(SSH용)
aws ec2 create-key-pair --key-name pharma-p5 --query KeyMaterial --output text > ~/.ssh/pharma-p5.pem
chmod 600 ~/.ssh/pharma-p5.pem

# 보안 그룹: 내 IP에서만 22(SSH), 8000(API)
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 create-security-group --group-name pharma-p5 --description "pharma p5 temp" \
      --vpc-id "$VPC" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22   --cidr "$MYIP/32"
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 8000 --cidr "$MYIP/32"

# 인스턴스: arm64(t4g.small), 디스크 16GB, 종료=삭제, 3시간 뒤 자동 종료(user-data)
AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
      --query Parameter.Value --output text)
IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type t4g.small --key-name pharma-p5 \
      --security-group-ids "$SG" --instance-initiated-shutdown-behavior terminate \
      --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp3,DeleteOnTermination=true}' \
      --user-data file://deploy/user-data.sh \
      --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=pharma-p5}]' \
                           'ResourceType=volume,Tags=[{Key=Project,Value=pharma-p5}]' \
      --query 'Instances[0].InstanceId' --output text)

# 철거에 쓸 값을 파일에 저장(터미널을 닫아도 남도록)
printf 'export AWS_REGION=%s\nIID=%s\nSG=%s\n' "$AWS_REGION" "$IID" "$SG" > ~/.pharma-p5-ids
cat ~/.pharma-p5-ids

aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "서버 IP: $IP"
```
**서버가 3시간 뒤 스스로 종료·삭제된다**(user-data의 `shutdown -h +180`과 `terminate` 설정). 그래도 5장 이후 작업이 끝나면 9장으로 직접 철거한다.

> 내 공인 IP는 네트워크를 옮기면(카페, 핫스팟 등) 바뀐다. 접속이 안 되면 11장 참고.

## 7. 서버에 올리고 띄우기

**(맥북) 소스와 비밀·데이터 올리기**
```bash
git archive --format=tar.gz -o /tmp/pharma-src.tgz HEAD     # 커밋된 파일만. deploy.env·덤프는 포함되지 않는다
scp -i ~/.ssh/pharma-p5.pem /tmp/pharma-src.tgz deploy/deploy.env deploy/pharma.sql.gz ec2-user@"$IP":~/
ssh -i ~/.ssh/pharma-p5.pem ec2-user@"$IP"
```
처음 접속하면 호스트 지문 확인 질문에 `yes`.

**(서버 안에서)**
```bash
cloud-init status --wait            # user-data(Docker 설치)가 끝날 때까지 기다린다. "status: done"이면 됨
docker compose version              # 버전이 나와야 한다

mkdir app && tar -xzf pharma-src.tgz -C app
mv deploy.env pharma.sql.gz app/deploy/
cd app
DC="docker compose -f deploy/compose.deploy.yaml --env-file deploy/deploy.env"

$DC up -d db                        # DB만 먼저
deploy/restore_db.sh deploy/pharma.sql.gz    # 역할 생성 + 데이터 복원. 마지막에 행 수가 출력된다
$DC up -d --build api               # 이미지 빌드(처음에는 몇 분) 후 실행
$DC ps                              # db, api 모두 healthy여야 한다
curl -s localhost:8000/ready        # {"status":"ready", ...}
```
`restore_db.sh`는 **한 번만** 실행한다(다시 실행하면 역할이 이미 있다는 오류).

## 8. 외부에서 검증 (맥북, 서버 밖)

```bash
KEY=$(grep '^PHARMA_API_KEY=' deploy/deploy.env | cut -d= -f2)

curl -i  http://$IP:8000/health                         # 200
curl -s  http://$IP:8000/ready                          # ready, 3개 체크 ok
curl -i -X POST http://$IP:8000/ask -H "Content-Type: application/json" \
     -d '{"question":"q"}'                              # 401 (키 없음)
curl -s -X POST http://$IP:8000/ask -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
     -d '{"question":"창고 WH-INC의 가용 재고 총량(단위)은 얼마인가?"}'    # 답: 189779
```
성공 기준: 위 4개가 기대대로 나오고, 서버의 로그에서 같은 요청 ID가 찾아진다.
```bash
ssh -i ~/.ssh/pharma-p5.pem ec2-user@"$IP" \
  'cd app && docker compose -f deploy/compose.deploy.yaml --env-file deploy/deploy.env logs --tail 20 api'
```
기록해 둘 것: 각 응답의 HTTP 상태, `/ask`의 `latency_ms`(서버 측)와 맥북에서 잰 총 시간(`curl -w '%{time_total}'`)의 차이, 토큰 수.

선택: 다른 네트워크(휴대폰 핫스팟)에서 같은 주소로 `/health`를 호출하면 **연결이 안 되어야** 한다. 보안 그룹이 내 IP만 허용한다는 확인이다.

## 9. 철거 (반드시, 확인까지)

```bash
source ~/.pharma-p5-ids
aws ec2 terminate-instances --instance-ids "$IID"
aws ec2 wait instance-terminated --instance-ids "$IID"
aws ec2 delete-security-group --group-id "$SG"
aws ec2 delete-key-pair --key-name pharma-p5
rm -f ~/.ssh/pharma-p5.pem
```

**철거 확인** (모두 비어 있거나 `terminated`여야 한다)
```bash
source ~/.pharma-p5-ids
aws ec2 describe-instances --filters Name=tag:Project,Values=pharma-p5 \
    --query 'Reservations[].Instances[].State.Name'        # ["terminated"]
aws ec2 describe-volumes --filters Name=tag:Project,Values=pharma-p5 --query 'Volumes[].VolumeId'   # []
aws ec2 describe-addresses --query 'Addresses[].PublicIp'                                           # []
aws ec2 describe-security-groups --filters Name=group-name,Values=pharma-p5 --query 'SecurityGroups[].GroupId'   # []
```
그리고
- Anthropic Console에서 **배포 전용 키를 삭제**한다.
- 맥북의 `deploy/deploy.env`와 `deploy/pharma.sql.gz`를 삭제한다(`rm`). 이 PC의 파일은 그대로 둔다.
- 다음 날 Billing 화면에서 실제 비용을 확인한다. 예산 알림은 두거나 삭제한다.

## 10. 끝난 뒤 기록

`docs/operations.md`에 다음을 추가한다(날짜, 리전·인스턴스 타입, 올려 둔 시간, 외부 호출 결과, 실제 비용, 철거 확인).

| 항목 | 기록할 값 |
|---|---|
| 날짜·리전·타입 | |
| 가동 시간 | |
| 외부 호출 결과 | `/health`, `/ready`, 401, `/ask` 정답 여부, 지연 |
| 실제 비용 | 철거 다음 날 확인한 값 |
| 철거 확인 | 9장 확인 명령 결과 |

**이력서·면접에서 말할 수 있는 것**: "AWS EC2에 Docker로 배포하고 외부에서 호출해 검증한 뒤 철거했다(보안 그룹으로 접근 제한, 비용 알림, 자동 종료 설정)."
**말하면 안 되는 것**: 상시 운영, HTTPS 적용, 고가용성·오토스케일링, 도메인 연결. 이번 배포에는 없다.

## 11. 문제 해결

| 증상 | 원인과 조치 |
|---|---|
| SSH·curl이 응답 없이 멈춤 | 내 공인 IP가 바뀜. 새 IP로 규칙 갱신: `aws ec2 revoke-security-group-ingress`로 옛 규칙 삭제 후 `authorize-security-group-ingress`로 새 `/32` 추가(22, 8000 모두) |
| `docker: permission denied` | 로그아웃 후 다시 접속하거나 `sudo docker ...` |
| `docker compose` 없음 | user-data 실패. `sudo cat /var/log/cloud-init-output.log`로 원인 확인. compose 바이너리 URL의 버전이 없으면 [docker/compose releases](https://github.com/docker/compose/releases)에서 최신 버전으로 바꿔 직접 설치 |
| 빌드 중 메모리 부족·종료 | `t4g.medium`으로 올리거나 다시 시도 |
| arm64 관련 빌드·실행 오류 | x86으로 바꾼다: 인스턴스 타입 `t3.small`, AMI 파라미터를 `...al2023-ami-kernel-default-x86_64`로 교체(`user-data.sh`는 아키텍처를 자동 감지) |
| `/ready`가 503 | 어느 체크가 `error`인지 본문 확인. `db_*`면 `restore_db.sh`가 끝났는지, 비밀번호가 `deploy.env`와 같은지 확인. `anthropic_api_key`면 키가 비었는지 확인 |
| `/ask`가 502·503 | 모델 서비스 오류. Anthropic 키·한도 확인(서버 로그에 `upstream_error`) |
| 비용 알림이 옴 | 원인 파악보다 **먼저 9장으로 철거**한다 |

## 보안 메모와 한계 (알고 쓴다)
- **HTTP(평문)**다. API 키가 암호화 없이 오간다. 그래서 ① 접근을 내 IP 하나로 제한하고 ② 이번 배포 전용 키를 쓰고 ③ 끝나면 폐기한다. TLS는 이 배포 범위에 없다.
- 비밀은 서버의 `deploy.env`(파일)에 있고 user-data에는 넣지 않았다(user-data는 인스턴스 메타데이터로 조회될 수 있다). 인스턴스가 삭제되면 디스크도 삭제된다.
- 서버 한 대라서 장애 대응이 없다. DB 데이터는 인스턴스와 함께 사라진다(원본은 이 PC에 있다).
- rate limit은 프로세스 메모리 안에서만 센다(서버 한 대라서 문제없음).
- `restart: "no"`라서 서버가 재부팅되면 컨테이너는 자동으로 다시 뜨지 않는다.
