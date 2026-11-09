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

