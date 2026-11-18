# 운영 요약 (P4, 2026-11-03)

개인 프로젝트 수준의 운영 장치다. **실제 서비스 운영 경험이 아니다.**

## 실행
```bash
# .env에 PHARMA_API_KEY=<임의의 긴 문자열>을 추가한다(예: python -c "import secrets;print(secrets.token_urlsafe(32))")
uv run uvicorn pharma_scm.api.main:app --host 0.0.0.0 --port 8000
curl -s localhost:8000/ask -H "X-API-Key: $PHARMA_API_KEY" -H "Content-Type: application/json" \
     -d '{"question": "SKU-001의 가용 재고 합계는?"}'
```
- `PHARMA_API_KEY`가 없으면 서버는 **시작하지 않는다**(인증 없이 띄우지 않음). 쉼표로 여러 키를 줄 수 있다.
- 설정(환경변수): `PHARMA_ASK_TIMEOUT_S`(기본 60), `PHARMA_RATE_LIMIT_PER_MIN`(키별, 기본 30), `PHARMA_MAX_CONCURRENCY`(기본 8).

## 엔드포인트
| 경로 | 인증 | 용도 |
|---|---|---|
| `GET /health` | 없음 | 생존(liveness). 프로세스가 응답하면 200. DB·모델이 죽어도 200 |
| `GET /ready` | 없음 | 준비(readiness). 읽기 전용 DB·조회 DB 연결과 모델 API 키 존재를 확인. 하나라도 실패하면 503. **모델 API를 호출하지는 않는다** |
| `POST /ask` | `X-API-Key` | `{"question": "..."}` (1~1000자) → 답, 호출한 도구, 토큰, 단계별 시간 |

## 장애 시 무엇이 어떻게 보이는가
오류 응답은 항상 `{"error": {"code", "message", "request_id"}}` 형식이고, `request_id`로 서버 로그를 찾는다.

| 상황 | HTTP | code | 로그(`msg`) | 비고 |
|---|---|---|---|---|
| API 키 없음/틀림 | 401 | `unauthorized` | `request`(status 401) | 키 원문은 로그에 남기지 않음(해시 앞 8자만) |
| 요청 형식 오류 | 422 | `bad_request` | `request` | 오류 응답에 입력 내용을 되돌려주지 않음 |
| 키별 요청 한도 초과 | 429 | `rate_limited` | `request` | `Retry-After` 헤더 |
| 전체 타임아웃 | 504 | `timeout` | `ask_timeout`(그때까지의 단계별 시간 포함) | 아래 한계 참고 |
| 도구 호출 상한(8회) 초과 | 508 | `loop_limit` | `ask_loop_limit` | 평가의 `loop_limit`과 같은 개념 |
| 모델이 빈 답 반환 | 502 | `empty_answer` | `ask_empty_answer` | 평가 E009·E010에서 본 증상 |
| 모델 서비스 연결·서버 오류 | 502 | `upstream_error` | `upstream_error`(예외 종류) | |
| 모델 서비스 요청 제한 | 503 | `upstream_rate_limited` | — | |
| 그 외 예외 | 500 | `internal_error` | `internal_error`(스택 트레이스) | 응답에는 상세 내용을 넣지 않음 |
| DB 연결 불가 | `/ready` 503 | — | — | `/health`는 계속 200이라 재시작 대상이 되지 않고 트래픽만 빠진다 |

## 로그
- stdout에 JSON 한 줄씩: `ts, level, logger, msg, request_id, ...`.
- 모든 요청에 `request`(method, path, status, duration_ms). `/ask` 성공 시 `ask`(question_chars, answer_chars, tools_called, tokens, latency_ms, **stages**: LLM·도구 호출별 ms).
- 요청 ID는 `X-Request-ID`를 받으면(영숫자·`_-`, 64자 이하) 그대로, 아니면 새로 만들어 응답 헤더로 돌려준다.
- **질문 본문은 로그에 남기지 않는다**(민감 정보 가능성). 대신 디버깅할 때 질문을 알 수 없다.

## 테스트
`uv run pytest -q` → DB가 있으면 36개 통과, 없으면 32개 통과 + 4개 건너뜀(DB가 필요한 `test_tools.py` 4개).
테스트는 **틀리면 피해가 큰 로직(보안·인증·비용 폭주·정보 유출·채점 신뢰도)만** 남겼다. 각 테스트 함수의 docstring에 무엇을 확인하는지 적었다.
- `test_api.py`(9개): 키 없이 시작 거부, 인증(401), 정상 경로, 타임아웃(504), 내부 오류 비노출, rate limit(429), 로그에 질문·키 비노출. LLM은 주입한 가짜 함수.
- `test_sql_guard.py`(15개): 위험·허용 밖 SQL 거부. `test_tools.py`(5개): 거부 SQL, 조회 결과·200행 절단, 결품 상태 구분(4개는 DB 필요).
- `test_graph.py`(2개): 거부된 SQL이 모델에 전달되는지, 도구 호출 루프 상한. `test_grader.py`(4개): 114문항 정답 통과·오답 거부, 마지막 `최종 답:`만 읽기, 숫자 허용 오차. `test_ratelimit.py`(1개).
- 정리 전에는 73개였다(요청 ID 형식, 검증 오류 형식, ready 검사, 단계별 시간, 허용 SQL 등 비교적 가벼운 확인 포함). 필요하면 커밋 `033cfc7`의 `tests/`에서 복구할 수 있다.
- CI(`.github/workflows/ci.yml`): ruff, pytest, docker build. **GitHub Actions에서 실행해 통과를 확인했다**(2026-11-06 push: ruff 통과, pytest 65 passed·8 skipped(테스트 정리 전 기준), docker build 성공). CI에는 원본 데이터와 Postgres가 없어 DB 테스트(4개)는 건너뛰므로, 그 부분은 CI가 검증하지 않고 로컬(DB를 띄운 상태)에서만 확인된다.

## 한 것 / 안 한 것 / 한계
- **한 것**: 위 장치 전부를 구현했고 로컬에서 테스트와 서버·컨테이너 실행(`/health`, `/ready`, 401)으로 확인했다.
- **실제 모델로 `/ask` 전 구간 확인(2026-11-06)**: 서버를 띄워 평가셋 질문 3개(SQL 조회 A001, 결품 조회 B001, SOP 검색 C001)를 보냈고 **셋 다 정답**이었다(200, 호출당 2회 LLM·도구 1회, 입력 약 4.7~5.2k·출력 약 0.2~0.3k 토큰, 응답 3.5~4.0초). 요청 ID로 로그를 찾으면 `ask`·`request` 두 줄이 나오고 질문 본문·키 원문은 로그에 없었다. 3건 표본이라 성능 수치로 쓰지 않는다.
- **안 한 것**: Prometheus 같은 **메트릭 엔드포인트**(지금은 로그의 `duration_ms`·`tokens`·`stages`로만 간접 파악), TLS, 부하 시험, 모델 호출 재시도 동작 자체의 테스트.
- **한계**:
  - 타임아웃이 나도 **작업 스레드는 취소되지 않고** 모델 호출이 끝날 때까지 계속 돈다(응답만 504). 자원과 비용이 새는 구조다.
  - rate limit은 **프로세스 메모리**에만 있다. 서버를 여러 대·여러 워커로 띄우면 한도가 그만큼 늘어난다.
  - 모델 호출 재시도는 Anthropic SDK의 내장 재시도(최대 2회, 지수 백오프)에 맡긴다. 직접 구현하지 않았다.
  - API 키는 환경변수에 평문으로 둔다. 회전·권한 구분이 없다(비밀 관리는 P5).
  - `/ready`는 모델 서비스 상태를 보지 않는다. 모델 장애는 `/ask`의 502/503으로만 드러난다.
  - 컨테이너 헬스체크의 최종 `healthy` 상태는 확인하지 못했다(점검 시점에 `starting`).

## P5 AWS 배포 기록 (2026-11-06)
절차는 `docs/deploy_p5.md`, 자동화는 `deploy/aws_up.sh`·`server_up.sh`·`aws_down.sh`. 임시 배포 후 철거했다(상시 운영 아님). Terraform으로 다시 한 기록은 아래 "P5 Terraform 재배포 기록"에 있다.

| 항목 | 기록 |
|---|---|
| 날짜·리전·타입 | 2026-11-06, ap-northeast-2(서울), `t4g.small`(arm64, Amazon Linux 2023), EBS gp3 16GB |
| 가동 시간 | 약 1시간 안팎(정확한 시간은 기록하지 않음). 3시간 자동 종료 설정 |
| DB 복원 | 행 수 기대와 일치(products 90, sales_orders 180,519, inventory_lots 228, shortage_events 1,622, sop_sections 30) |
| 검증 결과 | `/health` 200, `/ready` ready(3개 체크 ok), 키 없는 `/ask` 401, `/ask`(WH-INC 가용 재고) **정답 189779** |
| 지연·토큰 | 서버 측 3,403ms, 총 3.48초(SSH 터널 경유), 입력 4,713·출력 214 토큰, LLM 2회·도구 1회 |
| 실제 비용 | 실제 청구액 없음. 신규 계정의 무료 크레딧(100달러)으로 충당되어 비용이 거의 없다고 판단함. Billing 화면의 정확한 사용액은 확인하지 않음 |
| 철거 확인 | 인스턴스 `terminated`, 볼륨·탄력적 IP·보안 그룹 모두 없음. 키 쌍·pem 삭제 |

**문서와 다르게 한 점(솔직하게 적는다)**
- 접속한 네트워크가 휴대폰 핫스팟(통신사 NAT)이라 `/32` 허용만으로는 22번·8000번 접속이 타임아웃되었다. 원인은 목적지에 따라 출발 공인 IP가 달라서인 것으로 **추정**하며 확인하지는 않았다.
- 그래서 22번만 **임시로 `0.0.0.0/0`에 열어**(키 인증만 허용) 서버에 올렸고, 검증 직후 다시 `/32`로 닫았다.
- `/ask` 검증은 외부에서 8000번 직접 호출이 아니라 **SSH 터널(`-L 18000:localhost:8000`)** 로 했다. 따라서 "외부에서 직접 호출 검증"이 아니라 "터널 경유 검증"이다. 보안 그룹의 IP 제한 동작(다른 네트워크에서 차단)도 확인하지 않았다.
- `server_up.sh`는 `restore_db.sh`가 stdin을 소비해 이후 명령이 실행되지 않는 문제가 있어 `</dev/null`로 고쳤다. API 기동은 그 고치기 전에 수동으로 실행했다.
- HTTPS·상시 운영·고가용성·도메인 연결은 하지 않았다.

## P5 Terraform 재배포 기록 (2026-11-09)
같은 구성을 `deploy/terraform/`(Terraform)으로 만들어 검증하고 철거했다. 구성·사용법은 `deploy/terraform/README.md`, 위 2026-11-06 기록(스크립트 버전)과 같은 `deploy/server_up.sh`를 썼다. 임시 배포였고 상시 운영이 아니다.

| 항목 | 기록 |
|---|---|
| 날짜·리전·타입 | 2026-11-09, ap-northeast-2, `t4g.small`(arm64, Amazon Linux 2023), EBS gp3 16GB, IMDSv2 강제 |
| 만든 것 | 5개: 키 페어, 보안 그룹, 인스턴스, tls 키, 로컬 pem |
| 가동 시간 | 정확한 시간은 기록하지 않음. 3시간 자동 종료 설정, 그 전에 `terraform destroy`로 철거 |
| 검증 결과 | `/ready` ready(3개 체크 ok), 키 없는 `/ask` 401, `/ask`(WH-INC 가용 재고) 답 189779, `query_db` 1회, 약 3초, 입력 4,713·출력 215 토큰 |
| 실제 비용 | 무료. 신규 계정의 무료 크레딧으로 충당되어 청구액이 없다(11-06 기록과 같음). Billing 화면의 정확한 사용액은 기록하지 않음 |
| 철거 확인 | 인스턴스 `terminated`, 키 페어·보안 그룹·`Project=pharma-p5` 볼륨 없음, pem 삭제, `terraform state list` 비어 있음 |

**검증 범위의 한계 (11-06 기록과 다른 점)**
- `/ask`는 SSH 터널이 아니라 **공인 IP의 8000번 직접 호출**(`http://<IP>:8000/ask`, `X-API-Key` 헤더)로 했다. 호출한 곳은 `/32`로 허용한 같은 PC다. 11-06에 터널을 쓴 이유였던 핫스팟 문제는 이번에는 나타나지 않았다.
- `/32` 제한이 **허용되지 않은 IP에서 차단되는지는 확인하지 않았다.** 허용 IP에서 호출이 통과한 것과 키 없는 호출이 401인 것(앱 계층 인증)만 확인했다. 401은 보안 그룹이 아니라 앱이 돌려준 응답이다.
- `terraform plan`에서 보안 그룹 규칙이 22·8000번 모두 `/32` 하나뿐인 것은 확인했다. 22번을 `0.0.0.0/0`으로 연 일은 이번에는 없었다.
- 인스턴스는 `apply`로 만들었고, 이전 스크립트로 만든 리소스와는 겹치지 않았다.


## P6 비밀을 SSM에서 읽는 재배포 기록 (2026-11-13)
서버에 `deploy.env`를 복사하지 않고, 서버가 자기 IAM 역할로 SSM Parameter Store의 비밀을 읽도록 바꿔 배포했다. 서버는 `deploy/terraform/`으로 만들고 `deploy/server_up.sh`로 올렸고, **파라미터와 IAM 역할은 학습 목적으로 AWS 콘솔에서 만들고 붙였다**(절차는 `deploy/terraform/README.md` 맨 아래). 임시 배포였고 상시 운영이 아니다. 아래 결과는 **사용자가 맥북에서 실행해 이 세션에 붙여 준 출력**이며 이 PC에서 직접 돌린 것이 아니다.

| 항목 | 기록 |
|---|---|
| 날짜·리전·타입 | 2026-11-13, ap-northeast-2, `t4g.small`(Amazon Linux 2023, arm64), IMDSv2 강제 |
| 바뀐 것 | `server_up.sh`가 `deploy.env`를 scp하지 않고 서버의 `deploy/fetch_secrets.sh`를 실행. 이 스크립트가 `/pharma/api_key`·`/pharma/anthropic_api_key`를 SSM에서 읽고, DB 비밀번호 3개는 서버에서 새로 생성 |
| 만든 것 | Terraform: 키 페어·보안 그룹·인스턴스·tls 키·pem 5개. 콘솔: SSM `SecureString` 파라미터 2개, IAM 역할 `pharma-p5-ec2`(인라인 정책이 `ssm:GetParameter(s)`를 `parameter/pharma/*`에만 허용), 인스턴스에 역할 부착 |
| 확인한 것(사용자 출력) | 서버 안에서 `aws ssm get-parameter --name /other/x`가 `AccessDeniedException`(assumed-role `pharma-p5-ec2`, "no identity-based policy allows"). 서버에 `aws` CLI가 이미 있음. 키 교체 후 `/ask`(How many products)가 `query_db`를 거쳐 **90** 반환(호출 2회, 입력 4,638·출력 122 토큰, 2.1초). 키 없는 `/ask` 401 검증은 이 기록에서 별도로 보고되지 않음 |
| 철거 | 사용자가 "철거 완료"라고 보고했다. `terraform destroy`, SSM 파라미터 2개·IAM 역할 삭제, Anthropic 배포 전용 키 삭제를 안내했으나 **각 항목의 확인 출력(`describe-instances`, 인스턴스 프로파일 잔존 여부 등)은 받지 못했다** |
| 실제 비용 | 정확한 사용액은 기록하지 않음(신규 계정 무료 크레딧 범위로 보이나 확인하지 않음) |

**겪은 문제와 원인**
- **IAM 역할 생성 거부**: SSO 권한 세트 `PowerUserAccess`에는 IAM 작업이 없다. IAM Identity Center에서 `AdministratorAccess` 권한 세트를 추가해 콘솔에서만 쓰고, 터미널(`terraform`, CLI)은 `PowerUserAccess` 프로필로 썼다.
- **`terraform plan`이 `InvalidClientTokenId`로 실패(2회)**: `AWS_PROFILE`이 걸리지 않은 창에서 `~/.aws/credentials`의 `[default]` 옛 액세스 키가 쓰였다. 파일을 `credentials.bak`으로 옮기고 `AWS_PROFILE`을 지정해 해결했다. 철거할 때는 새 터미널에서 같은 에러가 다시 나 `AWS_PROFILE`을 다시 지정했다(원인은 사용자 환경 설명에 근거한 추정).
- **`/ask`가 `요청 형식 오류`(422)**: `curl` 명령의 줄바꿈 `\` 때문에 본문이 서버에 가지 않았다. 한 줄로 쓰자 해결됐다(서버 코드 `app.py`가 필드 이름 없는 422를 내는 것을 읽고 본문 누락으로 추정, 사용자가 줄바꿈 문제였다고 확인).
- **`/ask`가 `upstream_error`**: 서버 로그에 `AnthropicAuthenticationError`가 계속 찍혔다. SSM에 저장된 Anthropic 키 값이 유효하지 않았던 것이다(정확한 원인은 붙여넣기 오류 등으로 **확인하지 못함**). 콘솔에서 값을 덮어쓰고, 서버에서 `deploy.env`의 `ANTHROPIC_API_KEY` 한 줄만 `sed`로 바꿔 `api` 컨테이너를 재생성해 해결했다.
- **`docker compose logs`가 `DB_ADMIN_PASSWORD` 누락 에러**: `--env-file deploy/deploy.env`를 빼고 실행해서 생긴 것으로, 서버 문제가 아니다.

**한계·미확인**
- `fetch_secrets.sh`를 서버에서 다시 실행하면 DB 비밀번호 3개가 새로 생성되어, 이미 만들어진 DB와 맞지 않게 된다(키만 바꿀 때는 쓰지 않고 `sed`로 한 줄만 바꿨다). 이미 있는 `deploy.env`의 DB 비밀번호를 유지하도록 고치는 일은 **아직 하지 않았다**.
- **`kms:Decrypt` 없이 `SecureString`이 읽히는지**: 기본 키(`alias/aws/ssm`)로 읽기가 성공해 추가 권한은 필요 없었던 것으로 보이나, 이를 따로 시험하지는 않았다.
- 파라미터·역할·부착을 콘솔로 해서 **Terraform에 기록이 없다**. 같은 환경을 코드로 다시 만들려면 `iam.tf`가 필요하며 이전 방식은 커밋 `84bda6f`에 있다.
- `/32` 방화벽이 허용되지 않은 IP를 차단하는지, HTTPS, 상시 운영(원격 tfstate·CI/CD 배포·모니터링)은 이전 기록과 같이 하지 않았다.
- 서버 `aws` CLI의 기본 설치는 확인했으나(이번 서버 기준), 이미지(AMI) 버전이 바뀌면 달라질 수 있다.

## P7 ECS Fargate 콘솔 배포 기록 (2026-11-16 ~ 11-17)
EC2 한 대 방식을 **ECS Fargate + ALB + RDS PostgreSQL**로 바꿔 콘솔로 한 번 만들고 검증한 뒤 철거했다. 임시 배포이고 상시 운영이 아니다. 전체 순서·용어·`/ask` 한 건의 경로·명령 해설·겪은 문제는 `docs/ecs_deploy_walkthrough.md`에, 비용 추정과 철거 순서는 `docs/ecs_cost_and_teardown.md`에 있다. 아래 결과 중 AWS 쪽은 **사용자가 맥북 또는 콘솔에서 실행해 세션에 알려 준 결과**이고, 이 PC에서 직접 돌린 것은 로컬 이미지 기동과 복원 스크립트 시험이다.

| 항목 | 기록 |
|---|---|
| 구성 | ECR 이미지(amd64, 태그=git 해시, immutable) → ECS 서비스 1개(Fargate 0.5 vCPU/1GB) → 타깃 그룹(IP 방식, `/health`) ← ALB(HTTP 80). DB는 RDS `db.t4g.micro` 단일 AZ(퍼블릭 아님). 비밀 7개는 SSM SecureString, 실행 역할이 환경변수로 주입 |
| 복원 | RDS는 퍼블릭이 아니라 **일회성 ECS 태스크**(복원 이미지 `restore-<해시>`)로 덤프를 넣었다. 행 수 5개가 기대값과 일치(90 / 180519 / 228 / 1622 / 30) |
| 확인한 것 | 서비스 `ACTIVE`, 타깃 `healthy`, `/health` 200, `/ready` 200(DB 2개·키 ok, `sslmode=require` 접속 포함), 키 없는 `/ask` 401, 키를 넣은 `/ask` 정답 9(A016), 요청 ID가 붙은 JSON 로그가 CloudWatch에 기록됨 |
| 철거 | 사용자 보고 + 확인 명령 8개(`ecs list-clusters`, `elbv2 describe-load-balancers`, `rds describe-db-instances`·`describe-db-snapshots`, `ecr describe-repositories`, `logs describe-log-groups`, `ec2 describe-addresses`·`describe-network-interfaces`)가 모두 빈 결과. 보안 그룹·타깃 그룹 삭제 여부는 이 명령들로 확인되지 않았다 |
| 실제 비용 | RDS 생성 화면 견적은 인스턴스 월 $18.25 + 스토리지 월 $2.62(콘솔 표시값). 실제 사용액·켜 둔 시간은 **미기록** |

**겪은 문제**(상세는 walkthrough §6): 맥북 `AWS_PROFILE`에 `export`가 빠져 `InvalidClientTokenId` / 옛 `AWS_ACCESS_KEY_ID` 환경변수 / Docker 엔진 꺼짐 / 다른 리전에 보안 그룹 생성 / 태스크 정의의 이미지 태그 누락으로 리비전 2 생성 / `docker push`의 업로드 세션 오류(재시도로 해결) / Billing 화면은 루트가 IAM 접근을 활성화해야 열림 / 맥북 IP 변경으로 `/health` 시간 초과.

**한계·미확인**
- **HTTP 평문**(도메인이 없어 HTTPS 미적용). `sslmode=require`는 DB 연결을 암호화하지만 서버 인증서를 검증하지 않는다.
- ECS 서비스의 **서킷 브레이커 자동 롤백은 동작을 확인하지 못했다**(첫 배포라 되돌릴 리비전이 없었음).
- 태스크가 공인 IP를 가진다(NAT 미사용). 복원 태스크와 앱이 같은 실행 역할을 공유한다(역할이 `/pharma/*`를 읽을 수 있음, 앱 태스크 정의는 관리자 비밀번호를 연결하지 않음).
- 단일 AZ, 태스크 1개. 콘솔로 만들어 Terraform에 기록이 없다.
- 서울 리전의 ALB·Fargate 요금은 확인하지 못했다.
- **IP 제한 차단은 확인했다**: 맥북 IP가 바뀐 날 `/health`가 시간 초과되었고(허용 IP 수정 후 통과), 이 PC(허용되지 않은 IP)에서도 시간 초과였다. 지난 배포에서 미검증이던 항목이다.
