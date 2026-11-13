# Terraform 버전 (aws_up.sh / aws_down.sh 대응)

같은 구성을 선언형으로 만든 것이다. 맥북에서 `terraform`(또는 `tofu`)과 AWS 자격 증명이 필요하다.
서버에 앱을 올리는 단계는 그대로 `deploy/server_up.sh`를 쓴다.

```bash
cd deploy/terraform
terraform init
terraform plan  -var allowed_cidr="$(curl -s https://checkip.amazonaws.com)/32"   # 만들 것을 미리 본다
terraform apply -var allowed_cidr="$(curl -s https://checkip.amazonaws.com)/32"   # yes 입력
cd ../..
deploy/server_up.sh "$(terraform -chdir=deploy/terraform output -raw public_ip)"

# 검증 후 철거: 만든 것 전부 삭제
terraform -chdir=deploy/terraform destroy -var allowed_cidr=1.2.3.4/32
```

## 스크립트 버전과 다른 점
- ID를 파일에 기록하지 않는다. `terraform.tfstate`가 만든 리소스를 추적하고, 중간에 실패해도 `apply`를 다시 하면 이어간다.
- 철거는 `destroy` 한 번이다. 순서(인스턴스 → 보안 그룹 → 키)는 도구가 의존 관계로 정한다.
- 개인키는 로컬에서 생성해 `~/.ssh/pharma-p5.pem`에 쓴다(AWS에는 공개키만 등록). 개인키가 **tfstate에도 평문으로 들어가므로** tfstate는 커밋하지 않는다(.gitignore 처리됨).
- 허용 IP는 자동 조회하지 않고 필수 변수로 받는다. `0.0.0.0/0`은 검증으로 거부한다.
- IMDSv2를 강제한다.
- 안전장치(3시간 자동 종료, 종료 시 삭제, 볼륨 함께 삭제)는 그대로다.
- `destroy`가 끝났는지는 `aws ec2 describe-instances --filters Name=tag:Project,Values=pharma-p5`로 확인한다(`aws_down.sh`의 확인 4종과 같음).

## 검증 상태
맥북에서 `init` → `validate` → `plan` → `apply` → `deploy/server_up.sh` → `destroy`까지 실제로 실행해 확인했다.
- `apply`로 5개 리소스(키 페어, 보안 그룹, 인스턴스, tls 키, 로컬 pem)가 만들어졌다.
- 서버에서 `/ready`가 정상이었고, `/ask` 질문 1건에 `query_db`를 거쳐 답이 왔다. API 키 없이 호출하면 401이다.
- `destroy` 후 인스턴스 `terminated`, 키 페어·보안 그룹·볼륨 없음, pem 삭제를 확인했다.

실행할 때 알아둘 점:
- `plan`부터는 유효한 AWS 자격 증명이 필요하다. `~/.aws`에 프로필이 여러 개면 `AWS_PROFILE=<프로필>`을 지정한다.
- `server_up.sh` 전에 `deploy/deploy.env.example`을 복사해 `deploy/deploy.env`를 직접 만들어야 한다.
- `.terraform.lock.hcl`은 provider 버전 고정용이라 커밋한다.

운영 기록(검증 범위의 한계, 비용 칸 포함)은 `docs/operations.md`의 "P5 Terraform 재배포 기록"에 있다. 같은 `/ask` 검증이 터널이 아닌 8000번 직접 호출이었고, `/32` 차단 동작은 확인하지 못했다는 점도 거기에 적었다. 스크립트 버전의 기록은 같은 파일의 "P5 AWS 배포 기록"이다.

## 비밀은 SSM에서 읽는다 (6단계, 콘솔로 진행 · 맥북에서 처음 실행 · 미검증)
서버는 `deploy.env`를 복사받지 않고, 자기 IAM 역할로 SSM Parameter Store를 읽어 `deploy.env`를 만든다(`deploy/fetch_secrets.sh`). DB 비밀번호는 서버에서 새로 생성한다.
**파라미터와 역할은 Terraform이 아니라 AWS 콘솔에서 만들고 붙인다**(학습 목적). 따라서 `destroy`가 지워 주지 않으니 철거를 직접 한다. 화면별 절차는 `~/server-tutorial/step06_secrets.md`의 "콘솔 버전" B-1~B-5.

순서:
1. 콘솔(서울 리전): Parameter Store에 `/pharma/anthropic_api_key`(배포 전용 새 키), `/pharma/api_key`(`openssl rand -hex 24`로 만든 값)를 `SecureString`으로 만든다.
2. 콘솔: IAM 역할 `pharma-p5-ec2`(EC2용, 인라인 정책은 `ssm:GetParameter(s)`를 `parameter/pharma/*`에만 허용).
3. 맥북: `terraform apply`로 서버를 만든다.
4. 콘솔: EC2 → 인스턴스 `pharma-p5` → 작업 → 보안 → IAM 역할 수정 → `pharma-p5-ec2`.
5. 맥북: `deploy/server_up.sh <IP>` (**4번 뒤에** 실행해야 서버가 SSM을 읽을 수 있다).
6. 철거: `terraform destroy` 후 콘솔에서 파라미터 2개, IAM 역할(인스턴스 프로파일 잔존 여부 확인), Anthropic 배포 전용 키를 지운다.

- `server_up.sh`는 `git archive HEAD`로 소스를 올리므로 `fetch_secrets.sh`가 커밋된 상태여야 서버에 간다.
- 확인하지 못한 것: 서버의 `aws` CLI 기본 설치 여부, `kms:Decrypt` 불필요 여부, 역할 삭제 시 프로파일 동시 삭제 여부.
- Terraform으로 같은 일을 하는 방식(`aws_iam_role` 등)은 개념이 잡힌 뒤 옮긴다. 이력은 커밋 `84bda6f`의 `iam.tf`.
