# 7단계 ECS Fargate 배포 복습 노트 (2026-11-16 ~ 11-18)

철거 뒤 복습 시간에 **기억에 기대지 않고 읽기만 하면 되도록** 쓴 문서다. 무엇을 왜 했는지, 명령이 무슨 뜻인지, `/ask` 한 번이 어디를 거쳐 답이 되는지를 순서대로 적었다.

**근거 표기 규칙**
- **직접 확인**: 이 PC에서 Claude가 돌려서 본 것. 11-18부터는 이 PC(WSL)에 AWS CLI를 설치해 **AWS 조회도 여기에 포함**된다(§4-N)
- **사용자 보고**: 사용자가 맥북 또는 AWS 콘솔에서 실행해 세션에 알려 준 결과. 11-17까지는 AWS가 이 PC에서 호출이 안 되어(인증서 문제라고 알았음) 대부분 이쪽이다
- **알고 있는 기준**: 콘솔 메뉴 이름, AWS 동작 방식처럼 Claude가 직접 보지 못하고 알던 지식으로 안내한 것. 화면이 달랐던 곳은 해당 위치에 적었다

**콘솔 설정값에 대한 주의**: 콘솔에서 입력한 값(서킷 브레이커, 공인 IP, 삭제 옵션 등)은 Claude가 안내한 값이고 사용자가 그대로 따랐다고 보고했지만, 설정 화면 자체를 Claude가 본 것은 아니다. CLI 확인 명령이 있는 항목(태스크 정의, 타깃 그룹, ALB, 서비스 상태, RDS 속성)만 결과로 검증됐다.

**식별자 표기**: 저장소에 남지 않도록 계정 ID는 `<계정ID>`, ALB 주소는 `<ALB-DNS>`, RDS 주소는 `<RDS-엔드포인트>`로 적었다. 실제 값은 AWS 콘솔과 사용자의 기록에 있다.

---

## 1. 한 장 요약

**목표**: 지난 EC2 한 대 배포(서버에 SSH로 들어가 컨테이너 실행)를, 서버를 직접 다루지 않고 AWS가 컨테이너를 유지·교체해 주는 현업 표준 형태로 바꿔 본다.

```
맥북 ─HTTP 80─▶ ALB (pharma-alb)  ── 보안 그룹 pharma-alb-sg: 내 IP만 80 허용
                   │
                   ▼ 리스너 80 → 타깃 그룹
              타깃 그룹 (pharma-tg): IP 방식, 8000번, /health 통과한 태스크만 명단에 둠
                   │
                   ▼ 보안 그룹 pharma-task-sg: ALB에서 오는 8000만 허용
              태스크 = 컨테이너 api (포트 8000, FastAPI)      ← ECS 서비스 pharma-api가 1개 유지
                   ├─▶ RDS PostgreSQL (pharma-db, 5432)       ← 보안 그룹 pharma-rds-sg: 태스크 SG에서 온 것만
                   └─▶ Anthropic API (인터넷, 태스크의 공인 IP로 나감)

컨테이너가 뜨기 전에 (실행 역할 pharma-ecs-execution):
   ECR에서 이미지 받기 · SSM에서 비밀 읽어 환경변수로 넣기 · CloudWatch Logs로 로그 보내기
```

**이번에 정한 것**: DB는 RDS(현업 표준) / 이미지 CPU는 amd64 / 만드는 방식은 콘솔로 먼저 익히고 Terraform으로 옮기기 / 도메인이 없어 **HTTP**로 진행(한계로 기록).

**결과**: 맥북에서 `/ask`를 호출해 정답(9)을 받았다. 확인 후 전부 철거했다.

---

## 2. 용어집

| 용어 | 한 줄 정의 | Unity 비유 | 이 프로젝트의 실물 |
|---|---|---|---|
| 이미지 | 앱 실행에 필요한 모든 것을 묶은 설계도 파일 | 프리팹 | `pharma-scm-agent` 이미지(루트 `Dockerfile`로 빌드) |
| 컨테이너 | 이미지를 실행한 것 | 씬에 Instantiate한 오브젝트 | 태스크 안의 `api` 컨테이너 |
| ECR | AWS의 이미지 보관함 | Addressables 원격 서버 | 저장소 `pharma-scm-agent` |
| 태그 | 이미지의 버전 이름표 | 번들 버전 | 앱 `7b34645`, 복원 `restore-ede8677` |
| 태스크 정의 | "컨테이너를 이렇게 실행해라"를 적은 설정서 | 프리팹 인스턴스의 초기 설정 | `pharma-scm-agent`(리비전 3), `pharma-restore` |
| 리비전 | 태스크 정의의 버전 번호. 수정이 아니라 새 번호가 쌓임 | 세이브 슬롯이 쌓이는 것 | 앱은 1(태그 빠짐)→2→3(DSN 추가) |
| 태스크 | 태스크 정의대로 실제로 실행 중인 컨테이너 묶음 | 씬 안의 인스턴스 | 서비스가 띄운 1개, 복원용 일회성 1개 |
| 클러스터 | 태스크와 서비스를 담는 논리적 묶음 | 씬 | `pharma-cluster` |
| ECS 서비스 | "태스크를 N개 켜 둬라"를 유지하는 관리자 | 풀 매니저 | `pharma-api`(1개 유지) |
| Fargate | 컨테이너를 돌릴 서버를 AWS가 알아서 준비해 주는 방식 | 빌드 서버를 신경 쓰지 않는 것 | 이번 실행 방식 |
| 타깃 그룹 | 요청을 받을 수 있는 태스크들의 명단 + 헬스체크 | 접속 가능한 서버 목록 | `pharma-tg` |
| ALB | 인터넷 요청을 받아 타깃 그룹에 나눠 주는 문지기 | 로비 서버 | `pharma-alb` |
| 보안 그룹 | 자원마다 붙는 방화벽 규칙 | 출입 허가 목록 | `pharma-alb-sg`, `pharma-task-sg`, `pharma-rds-sg` |
| 실행 역할 | 컨테이너가 **뜨기 전에** ECS가 쓰는 권한(이미지 pull, 비밀 읽기, 로그) | 빌드 파이프라인 계정 | `pharma-ecs-execution` |
| SSM Parameter Store | 설정과 비밀을 보관하는 AWS 저장소 | 암호화된 설정 서버 | `/pharma/...` 파라미터 7개 |
| SecureString | 암호화되어 저장되는 파라미터 타입 | | 7개 모두 이 타입 |
| RDS | AWS가 운영해 주는 DB. SSH 접속 불가, 주소만 받아 씀 | 클라우드 세이브 | `pharma-db`(PostgreSQL 17) |
| DSN | DB 접속 정보를 한 줄로 쓴 문자열 | | `postgresql://계정:비밀번호@주소:5432/pharma?sslmode=require` |
| CloudWatch Logs | 컨테이너 로그가 모이는 곳 | 원격 Player.log 수집소 | 로그 그룹 `/ecs/pharma-scm-agent` |
| VPC / 서브넷 | AWS 안의 사설 네트워크 | | 이번에는 **기본 VPC**만 사용(설계하지 않음) |
| 리전 | AWS 데이터센터 지역. 자원은 리전별로 따로 존재 | | 서울 `ap-northeast-2` |
| 서킷 브레이커 | 새 배포의 태스크가 계속 실패하면 배포를 멈추고 되돌리는 ECS 기능 | | 서비스에 켬(동작은 **미검증**) |
| 헬스체크 | 주기적으로 `/health`를 호출해 살아 있는지 보는 것 | | 타깃 그룹이 수행 |

**자주 헷갈린 구분**
- **셸 변수 vs 환경변수**: `export`를 붙이지 않은 변수는 `aws` 같은 다른 프로그램에 전달되지 않는다(이번에 `AWS_PROFILE`로 겪음).
- **태스크 vs 서비스**: 태스크는 "한 번 실행된 것", 서비스는 "태스크를 계속 N개 유지하는 관리자". 복원은 태스크(한 번 하고 끝), 앱은 서비스.
- **`/health` vs `/ready`**: `/health`는 살아 있음, `/ready`는 DB·키까지 준비됨. ALB 헬스체크는 `/health`를 썼다(DB가 잠깐 흔들려도 태스크가 한꺼번에 빠지지 않게).
- **실행 역할 vs 태스크 역할**: 실행 역할은 컨테이너 시작 전 준비용, 태스크 역할은 앱이 AWS를 직접 부를 때 쓰는 것. 이번 앱은 AWS를 직접 부르지 않아 태스크 역할은 만들지 않았다.
- **레지스트리 주소 vs 저장소 주소**: 로그인은 `<계정ID>.dkr.ecr.<리전>.amazonaws.com`, 이미지 이름은 거기에 `/pharma-scm-agent:<태그>`가 붙는다.

---

## 3. `/ask` 한 건의 여정

검증한 질문: "기준일(2026-11-01)부터 29일 이내(...)에 유통기한이 도래하는 가용 로트는 몇 개인가?" → 정답 **9**(평가셋 A016).

**준비 단계 (컨테이너가 뜨기 전, 서비스가 태스크를 만들 때)**
1. ECS 서비스가 태스크 정의 `pharma-scm-agent:3`대로 Fargate 태스크를 만든다.
2. **실행 역할**이 ECR에서 이미지 `pharma-scm-agent:7b34645`를 받는다(공인 IP로 인터넷을 거침).
3. 실행 역할이 SSM에서 `/pharma/api_key`, `/pharma/anthropic_api_key`, `/pharma/ro_dsn`, `/pharma/ext_dsn` 4개를 읽어 **환경변수**(`PHARMA_API_KEY`, `ANTHROPIC_API_KEY`, `PHARMA_RO_DSN`, `PHARMA_EXT_DSN`)로 컨테이너에 넣는다.
4. 컨테이너가 시작된다. 앱은 시작할 때 `ANTHROPIC_API_KEY`가 없으면 즉시 실패한다(키가 빠진 배포가 헬스체크 전에 걸러짐).
5. 타깃 그룹이 `/health`를 15초마다 호출해 **두 번 연속 통과**(healthy 기준 2)하면 이 태스크를 명단에 올린다.

**요청 한 건**
1. 맥북이 `curl`로 `http://<ALB-DNS>/ask`에 POST. 헤더 `X-API-Key`(SSM에서 꺼내 넣음), 본문 `{"question": "..."}`.
2. 요청이 **ALB**에 도착. `pharma-alb-sg`가 **맥북의 현재 공인 IP만** 80번을 허용한다.
3. ALB 리스너(80)가 요청을 **타깃 그룹 `pharma-tg`**로 보낸다. 명단에 있는 healthy한 태스크의 8000번으로 전달.
4. `pharma-task-sg`가 **ALB의 보안 그룹에서 온 8000번만** 허용한다(인터넷에서 태스크로 직접 접근 불가).
5. **앱(FastAPI)**이 받는다: 요청 ID 생성 → `X-API-Key` 검사(`PHARMA_API_KEY`와 비교, 없거나 틀리면 401) → rate limit·타임아웃 적용.
6. **에이전트**(LangGraph)가 시작된다. 질문을 보고 Anthropic API(모델)를 호출한다. 이 호출은 태스크의 **공인 IP**를 통해 인터넷으로 나가고 `ANTHROPIC_API_KEY`를 쓴다.
7. 모델이 SQL 도구(`query_db`)를 쓰기로 하면, 앱이 `PHARMA_RO_DSN`(읽기 전용 계정 `pharma_ro`)으로 **RDS**에 접속해 SELECT를 실행한다. 이때 `pharma-rds-sg`가 **태스크 보안 그룹에서 온 5432번만** 허용하고, 연결은 `sslmode=require`로 암호화된다. 계정 설정이 읽기 전용이라 쓰기는 거부된다.
8. SQL 결과(9)가 모델에 돌아가고, 모델이 최종 답문을 만든다. (이번 응답의 도구 호출 내역은 확인하지 않았다. A016은 SQL 질문이라 `query_db`를 거쳤을 것으로 본다.)
9. 앱이 JSON 응답을 만든다 → 태스크 → 타깃 그룹 → ALB → 맥북.
10. 같은 시간 동안 앱의 JSON 로그(요청 ID 포함)가 컨테이너 출력으로 나가고, `awslogs`가 **CloudWatch Logs `/ecs/pharma-scm-agent`**로 보낸다(스트림 접두어 `api`).

**누가 어떤 비밀을 쓰나**
| 비밀 | 쓰는 곳 | 어디서 받나 |
|---|---|---|
| `PHARMA_API_KEY` | 앱(요청 인증) | SSM → 실행 역할 → 환경변수 |
| `ANTHROPIC_API_KEY` | 앱(모델 호출) | 같음 |
| `PHARMA_RO_DSN`, `PHARMA_EXT_DSN` | 앱(RDS 접속) | 같음 |
| DB 마스터 비밀번호 | **복원 작업만** | SSM → 실행 역할 → 복원 태스크의 환경변수 |

---

## 4. 시간순 작업 기록

### A. 개념 정리와 결정 (11-16)
- 개념 설명 순서: RDS → ECS·Fargate → 이미지·ECR·태스크 정의 → 서비스·타깃 그룹·ALB.
- 결정: DB는 RDS(비용보다 현업 표준 경험 우선), CPU amd64(이 PC와 CI 러너가 x86, 8단계 빌드와 일치), 방식은 콘솔 → Terraform, HTTP(도메인 없음).
- 앱 코드 점검(읽은 범위): 비밀과 DB 주소를 환경변수로 받는 것은 정석이다. 정석과 다른 점은 `config.py`의 DSN 기본값에 로컬 비밀번호가 있어 운영에서 환경변수를 빠뜨리면 조용히 로컬 주소로 간다는 것(고치지 않음).

### B. 이 PC에서 사전 확인 (직접 확인)
| 확인 | 결과 |
|---|---|
| `docker build --platform linux/amd64 -t pharma-scm-agent:local .` | amd64, 약 544MB(풀린 크기) |
| 환경변수만 주고 컨테이너 실행 | `/health` 200, `/ready` 200(DB 2개·키 ok), 키 없는 `/ask` 401, Dockerfile HEALTHCHECK healthy |
| `ANTHROPIC_API_KEY` 없이 실행 | 시작 단계에서 실패(`.env에 ANTHROPIC_API_KEY가 없다`). 의도된 동작 |
| 유휴 메모리 | 약 156MiB → 태스크 크기 0.5 vCPU / 1GB로 시작 |

이미지는 비밀과 DB 주소를 실행 시점 환경변수로만 받는다는 것이 확인되어 ECS 태스크 정의로 그대로 이어졌다.

### C. 비용·철거 계획 문서 (직접 작성 + 웹 검색)
- `docs/ecs_cost_and_teardown.md`를 만들기 전에 작성. 요금 페이지에 접속하지 못해(인증서) 서울 요금은 미확인으로 표시했다.
- 이후 RDS 생성 화면의 "예상 월 비용"으로 인스턴스 $18.25, 스토리지 $2.62(합계 $20.87/월)를 확인해 문서에 반영(사용자 보고).

### D. 맥북 AWS 인증 (사용자 보고, 겪은 문제 참고)
- `export AWS_PROFILE=pharma-p5`를 `~/.zshrc`에 `export` 붙여 영구 설정. `aws sts get-caller-identity`로 확인.

### E. ② ECR과 이미지 push
- 콘솔: ECR → Private repositories → `pharma-scm-agent`, **Tag immutability: Enabled**(같은 태그로 덮어쓰기 금지, 태그가 곧 커밋).
- 맥북(M2, arm64)에서 빌드·push. 명령은 아래 "5. 명령 해설"에 상세.
- 확인: `describe-images`에서 태그 확인, `docker image inspect`의 Architecture가 `amd64`.

### F. ③ 태스크 정의 준비물 (콘솔)
1. **③-1 실행 역할** `pharma-ecs-execution`: 신뢰 대상 `ecs-tasks.amazonaws.com`, AWS 관리형 `AmazonECSTaskExecutionRolePolicy`(ECR pull과 로그 쓰기), 인라인 정책 `ssm-read-pharma`(`ssm:GetParameters`를 `parameter/pharma/*`에만 허용). IAM은 `AdministratorAccess` 권한 세트로만 가능하다.
2. **③-2 로그 그룹** `/ecs/pharma-scm-agent`, **보존 7일**(기본은 무기한이라 용량 과금이 계속됨). 로그 그룹은 미리 만들어 두는 쪽이 실행 역할에 `logs:CreateLogGroup`을 주지 않아도 되어 권한이 더 좁다(알고 있는 기준).
3. **③-3 비밀 5개**(SecureString): 기존 `/pharma/api_key`, `/pharma/anthropic_api_key`(6단계에서 만듦) 확인 + `/pharma/db_admin_password`, `/pharma/db_ro_password`, `/pharma/db_ext_password`를 새로 만듦. 값은 `printf %s "$(openssl rand -hex 16)" | pbcopy`로 클립보드에 넣어 콘솔에 붙여 넣었다(채팅과 화면에 값이 나오지 않음, 줄바꿈 없음, 파라미터마다 새로 생성).
4. **③-4 태스크 정의** `pharma-scm-agent`(JSON 붙여넣기): Fargate, `awsvpc`, 0.5 vCPU/1GB, **`cpuArchitecture: X86_64`**, 컨테이너 `api`(8000), `secrets`, `awslogs`. 처음 등록은 이미지 태그를 빠뜨려 **리비전 1이 잘못 만들어졌고**, 고쳐 등록해 리비전 2가 되었다. 나중에 DSN 두 개를 더해 리비전 3.

### G. 계정 준비 (사용자 보고)
- AWS Budgets 월 $10 알림 생성. 결제 화면은 기본적으로 IAM 사용자·역할에 닫혀 있어 **루트 사용자로 로그인해 "IAM user and role access to Billing information"을 활성화**한 뒤 관리자 계정에서 열림.
- 이전 배포 잔여물(EC2, Elastic IP, 볼륨) 없음 확인.
- 기본 VPC 존재 확인(`describe-vpcs --filters Name=isDefault,Values=true`).

### H. ④-1 보안 그룹 3개
| 이름 | 허용 | 출처 |
|---|---|---|
| `pharma-alb-sg` | TCP 80 | 내 IP/32 |
| `pharma-task-sg` | TCP 8000 | `pharma-alb-sg` |
| `pharma-rds-sg` | TCP 5432 | `pharma-task-sg` |
- 출처를 IP 대신 **다른 보안 그룹**으로 지정하는 것이 현업 방식(태스크 IP가 바뀌어도 규칙이 유지됨).
- 처음에 다른 리전에 만들어 서울에서 다시 만들었다(겪은 문제 참고).

### I. ④-2 RDS 생성 (콘솔)
| 항목 | 값 |
|---|---|
| 엔진 | PostgreSQL 17(확인된 버전 17.11), **Aurora 아님** |
| 템플릿·가용성 | Dev/Test, 단일 AZ |
| 인스턴스 | `db.t4g.micro` (RDS 서버의 CPU는 amd64 이미지와 무관) |
| 저장소 | gp3 20GiB, **자동 확장 끔** |
| 접속 | 마스터 `pharma_admin`, 비밀번호는 SSM 값, **초기 DB 이름 `pharma`**(비우면 DB가 안 만들어짐) |
| 네트워크 | 기본 VPC, **퍼블릭 액세스 No**, 보안 그룹 `pharma-rds-sg`만 |
| 기타 | 자동 백업 1일, 삭제 방지 끔, Performance Insights·향상된 모니터링 끔 |
- 확인(사용자 보고): 엔진 `postgres 17.11`, `db.t4g.micro`, 단일 AZ, 퍼블릭 아님. 생성 직후 상태 `backing-up`은 첫 자동 백업 중이라 정상.

### J. ④-3 DB 복원 (일회성 ECS 태스크)
**왜 이 방식인가**: RDS는 퍼블릭이 아니라 맥북에서 직접 접속할 수 없다. 같은 VPC 안에서 한 번 실행하고 끝나는 태스크로 덤프를 넣는 것이 현업의 마이그레이션·시드 작업 방식과 같다.
1. `deploy/rds_restore.sh`(역할 생성 → 덤프 복원 → 읽기 전용 설정 → 행 수 출력), `deploy/restore.Dockerfile`(`postgres:17` + 스크립트 + 덤프, `ENTRYPOINT` 덮어쓰기), `deploy/.dockerignore`(허용 목록).
2. **이 PC에서 임시 `postgres:17` 컨테이너로 시험(직접 확인)**: 1회차 복원, 2회차는 중복 방지로 중단(종료코드 1), `pharma_ro`·`pharma_ext` 모두 읽기만 되고 DELETE는 `cannot execute DELETE in a read-only transaction`으로 거부. 이미지 자체로도 실행해 같은 행 수를 확인. 환경변수 누락 시 즉시 실패.
3. 커밋 `ede8677`로 저장소에 올리고 맥북에서 `restore-ede8677` 태그로 빌드·push(같은 ECR 저장소).
4. 태스크 정의 `pharma-restore`(0.25 vCPU/1GB, `PGHOST` 등은 일반 환경변수, 비밀번호 3개는 `secrets`).
5. 클러스터 `pharma-cluster`(Fargate만, Container Insights 끔) 생성 후 **Run new task**: 보안 그룹 `pharma-task-sg`, **공인 IP 켬**, Application type은 Task.
6. **결과(사용자 보고)**: 로그 마지막이 `완료`, 행 수 `products 90 / sales_orders 180519 / inventory_lots 228 / shortage_events 1622 / sop_sections 30`이 기대값과 일치.
- 이 실행으로 RDS 특유의 가정(마스터 권한으로 복원 가능, SSL 접속, 네트워크 경로)이 확인되었다.

### K. DSN 파라미터와 앱 태스크 정의 리비전 3
- 앱은 DB 접속을 DSN 한 줄로 받고 ECS는 파라미터를 이어 붙이지 못하므로, **DSN 전체가 파라미터 한 개**여야 한다. `/pharma/ro_dsn`, `/pharma/ext_dsn`을 `?sslmode=require`와 함께 만들었다(값은 클립보드로 붙여 넣음).
- `sslmode=require`: SSL이 안 되면 접속을 실패시킨다(기본 `prefer`는 평문으로 내려갈 수 있음). 서버 인증서 검증은 하지 않는다(한계).
- 앱 태스크 정의에 `PHARMA_RO_DSN`, `PHARMA_EXT_DSN` `secrets`를 추가한 **리비전 3**.

### L. ④-4 타깃 그룹과 ALB
- **타깃 그룹 `pharma-tg`**: 대상 유형 **IP**(Fargate는 태스크마다 IP를 받음), HTTP 8000, 헬스체크 `/health`, healthy 2회, 간격 15초, **등록 해제 지연 30초**(기본 300초는 배포·철거를 느리게 함).
- **ALB `pharma-alb`**: 인터넷 대상, 서로 다른 AZ 서브넷 2개 이상(필수), 보안 그룹 `pharma-alb-sg`, 리스너 HTTP:80 → `pharma-tg`, **idle timeout 120초**(앱의 `/ask` 제한이 60초이고 ALB 기본도 60초라 느린 질문에서 ALB가 먼저 끊을 수 있어서).
- 확인(사용자 보고): 리비전 3의 이미지·비밀 이름 4개, 타깃 그룹 `ip 8000 /health`, ALB `active internet-facing`.

### M. ④-5 ECS 서비스와 검증
- 서비스 `pharma-api`: 태스크 정의 리비전 3, 1개 유지, 롤링 업데이트, **배포 서킷 브레이커 + 실패 시 롤백 켬**, 헬스체크 유예 60초, 보안 그룹 `pharma-task-sg`, 공인 IP 켬, ALB·타깃 그룹 연결(`api 8000`).
- 확인(사용자 보고): 서비스 `ACTIVE`, 타깃 `healthy`(Reason 칸의 `None`은 문제가 없다는 뜻).
- 호출 검증(사용자가 맥북에서 실행): `/health` 200, `/ready` 200(DB 2개·키 ok), 키 없는 `/ask` 401, 키를 넣은 `/ask`가 **정답 9**. CloudWatch 로그에 **요청 ID가 붙은 JSON 로그**가 찍힘.
- **IP 제한 차단이 실제로 확인됨**: 다음 날 맥북의 공인 IP가 바뀌어 `/health`가 시간 초과 → 허용 IP를 현재 값으로 고치니 통과. 이 PC(허용되지 않은 IP)에서도 같은 요청이 10초 후 시간 초과(종료코드 28). 지난 배포에서 미검증이던 `/32` 차단이 이번에 확인됐다.

### N. 로드 밸런싱 연습 (11-18, 이름 앞에 `lbtest-`)
**목적**: 서비스의 로드 밸런싱 설정이 "타깃 그룹이 서버를 아는" 과정을 어떻게 만드는지, 콘솔로 다시 만들며 직접 보기. 공개 `nginx` 이미지를 써서 ECR·RDS·SSM·IAM 실행 역할 없이 진행했다. 만든 순서와 철거는 아래와 같고 **모두 철거했다**.

**이 PC에서 AWS를 쓸 수 있게 됨(직접 확인)**
- `sts.<리전>.amazonaws.com`에 `curl`이 응답하고 인증서 발급자도 Amazon이었다. 11-17까지 "이 PC에서 AWS 호출 불가"라고 적은 것은 **요금 페이지 등 다른 주소의 인증서 오류를 AWS 전체로 일반화한 것**이었을 수 있다(어느 주소가 막혔는지는 이번에 가리지 않음).
- AWS CLI v2(2.41.0)를 `~/.local`에 설치(관리자 권한 없이), SSO로 로그인, 프로파일 이름은 `pharma-lbtest`.

**구성**(CLI 조회로 값 확인)
| 자원 | 설정 |
|---|---|
| 보안 그룹 `lbtest-alb-sg` | 인바운드 TCP 80, 소스 `<내 IP>/32` |
| 보안 그룹 `lbtest-task-sg` | 인바운드 TCP 80, 소스 `lbtest-alb-sg`(보안 그룹 체이닝) |
| 클러스터 `lbtest-cluster` | Fargate, Container Insights 꺼짐 |
| 태스크 정의 `lbtest-nginx:1` | Fargate, `awsvpc`, 0.25 vCPU/0.5GB, X86_64, 이미지 `public.ecr.aws/nginx/nginx:stable`(amd64 포함을 레지스트리에서 확인), 컨테이너 `web` 80, 실행 역할·로그 없음 |
| 타깃 그룹 `lbtest-tg` | IP 유형, HTTP 80, 헬스체크 `/`, healthy 2회, 간격 15초, 등록 해제 지연 30초 |
| ALB `lbtest-alb` | 인터넷 대상, 서브넷 2개(2a·2b), `lbtest-alb-sg`, 리스너 HTTP:80 → `lbtest-tg`, idle timeout 기본 60초 |
| 서비스 `lbtest-svc` | `lbtest-nginx:1`, FARGATE(Spot 아님), 태스크 1개, 서브넷 2a·2b, `lbtest-task-sg`, 공인 IP 켬 |

**확인한 것(직접 확인)**
1. **서비스가 태스크 IP를 타깃 그룹에 자동 등록한다.** 타깃 그룹을 만들 때 대상은 비워 뒀고(조회 결과 `[]`), 서비스가 태스크를 시작하자 그 사설 IP가 나타나 `healthy`가 됐다. `describe-tasks`의 `privateIPv4Address`와 `describe-target-health`의 IP가 같았다. 태스크가 교체되면 옛 IP는 `draining`(`Target.DeregistrationInProgress`)을 거쳐 사라졌다.
2. **서비스 설정에 저장된 로드 밸런싱 값은 타깃 그룹 ARN, 컨테이너 이름, 컨테이너 포트 세 개**다(`describe-services`의 `loadBalancers`). ALB와 리스너는 서비스에 저장되지 않는다. 콘솔의 "기존 로드 밸런서 → 리스너 → 타깃 그룹" 선택은 타깃 그룹을 찾는 경로다.
3. **ALB와 태스크의 AZ가 어긋나면 태스크가 교체된다.** 첫 서비스는 서브넷 4개(2a~2d)를 모두 써서 태스크가 **2d**에 놓였다. ALB는 2a·2b에만 있었고, 그 태스크의 타깃 상태는 `unused`였고 `Task failed ELB health checks`(`ServiceSchedulerInitiated`)로 ECS가 중지했다. 교체된 태스크는 2b에서 `healthy`. **`unused`의 사유 문구는 조회에 나오지 않아 "AZ 불일치가 원인"은 추정**이다. 두 번째 서비스는 서브넷을 2a·2b로 줄여 문제없이 `healthy`가 됐다.
4. **ALB는 `active`가 된 뒤에도 노드(ENI)가 하나씩 늦게 생겼다.** 처음에는 2b에만 있었고 몇 분 뒤 2a도 생겼다.
5. **IP 제한은 실제로 동작하지만, 이 회사 네트워크에서는 `/32`가 맞지 않았다.** 보안 그룹에 `<내 IP>/32`만 있을 때 이 PC(WSL)와 윈도우 브라우저 모두 10초 시간 초과였다. `checkip.amazonaws.com`이 알려 주는 IP는 같은 값이었는데도 그랬다. 사용자가 콘솔에서 `0.0.0.0/0`을 **임시로** 추가하자 접속됐다(사용자 보고). 임시 규칙을 지운 뒤 `/32`만 남은 것을 조회로 확인했고(직접 확인) 같은 요청이 다시 시간 초과였다(직접 확인). 즉 **보안 그룹은 의도대로 걸러내고, ALB가 본 이 PC의 출발 IP가 `checkip`의 값과 다르다.** 왜 다른지(목적지에 따라 다른 외부 IP를 쓰는 회사 NAT 등)는 확인하지 못했다. 지난번 맥북에서는 `/32`가 통과했으니 이 네트워크의 특성이다.

**확인하지 못한 것**
- 서비스를 만들기 **전** ALB가 503(명단이 비어 있음)을 주는지: ALB 노드가 준비되기 전이었고 연결 자체가 시간 초과여서 보지 못했다.
- nginx 환영 페이지의 응답 내용: 사용자가 임시 개방 때 접속된다고 보고했지만 Claude가 응답 본문을 직접 보지는 못했다.

**이름·기본값 실수와 처리**
- 타깃 그룹을 `lbtest-sg`로 잘못 입력해 **이름은 바꿀 수 없어서** 삭제하고 `lbtest-tg`로 다시 만들었다. 다시 만든 그룹에 healthy 5회·간격 30초·등록 해제 지연 300초(기본값)가 남아 있어서 15초·2회·30초로 고쳤다(기본값이면 healthy까지 약 150초, 철거 때 5분 대기).
- 서비스 이름 칸을 건드리지 않아 기본값 `pharma-scm-agent-service-<접미사>`로 만들어졌고, 삭제 후 `lbtest-svc`로 다시 만들었다. 다시 만든 서비스는 **헬스체크 유예가 0초**로 들어갔다(의도는 30초). nginx는 빨리 떠서 영향이 없었지만 앱을 올릴 때는 60초 정도가 필요하다.

**철거(직접 확인)**: 클러스터·서비스·ALB·타깃 그룹·ENI·탄력적 IP·로그 그룹 모두 없음, CloudFormation 스택 없음(콘솔이 클러스터 생성 때 남기는 스택은 없었음), `lbtest-*` 보안 그룹 삭제됨. 비용 실측(켜 둔 시간, Billing 사용액)은 **미기록**.

---

## 5. 명령 해설

### 맥북에서 이미지 올리기
| 명령 | 역할 |
|---|---|
| `git pull`, `git log -1 --format=%h` | 최신 코드를 받고 현재 커밋의 짧은 해시를 확인. 해시가 태그가 됨 |
| `export ACCOUNT=...`, `export REPO=...`, `export TAG=...` | 반복해서 쓸 값을 변수로. `REPO`는 `계정ID.dkr.ecr.리전.amazonaws.com/저장소이름` |
| `aws ecr get-login-password ... \| docker login --username AWS --password-stdin <레지스트리>` | ECR용 임시 비밀번호(약 12시간 유효)를 만들어 docker에 전달. 비밀번호가 명령줄과 셸 이력에 남지 않게 `--password-stdin` 사용 |
| `docker build --platform linux/amd64 --provenance=false -t $REPO:$TAG .` | **amd64 이미지**를 빌드(M2는 기본이 arm64라 필수), 빌드 증명 정보 제외, `저장소주소:태그` 이름표 부여 |
| `docker push $REPO:$TAG` | ECR에 업로드. 이미 있는 레이어는 건너뜀. 태그가 immutable이라 같은 태그로 다시 올리면 거부됨 |
| `aws ecr describe-images ...` | **서버(ECR) 쪽에서** 이미지가 실제로 있는지 확인 |
| `docker image inspect ... --format '{{.Architecture}}'` | 로컬 이미지가 `amd64`인지 확인 |
| (복원 이미지) `docker build ... -f deploy/restore.Dockerfile -t $REPO:restore-<해시> deploy` | 빌드 컨텍스트가 `.`이 아니라 **`deploy` 폴더**(루트 `.dockerignore`가 `deploy`를 제외하기 때문) |

### 비밀·확인
| 명령 | 역할 |
|---|---|
| `printf %s "$(openssl rand -hex 16)" \| pbcopy` | 비밀번호를 만들어 **화면에 출력하지 않고** 클립보드로. 16진수라 DSN에 특수문자 인코딩이 필요 없음 |
| `aws ssm describe-parameters --query 'Parameters[].[Name,Type]' --output table` | 파라미터 **이름과 타입만** 확인(값은 안 나옴) |
| `printf 'postgresql://...%s...' "$(aws ssm get-parameter ... --with-decryption ...)" \| pbcopy` | DSN 전체를 만들어 클립보드로 |
| `aws ecs describe-task-definition --task-definition <이름>[:리비전] --query ...` | 등록된 태스크 정의의 리비전·크기·아키텍처·이미지 확인. 리비전을 생략하면 최신 활성 리비전 |
| `aws ecs describe-services ...`, `aws elbv2 describe-target-health ...` | 서비스가 원하는 개수로 돌고 있는지, 타깃이 healthy인지 |
| `aws logs tail /ecs/pharma-scm-agent --since 30m` | CloudWatch 로그 출력 |
| `curl -s -w ' [%{http_code}]\n' http://<ALB-DNS>/health` | `-w`는 요청 후 정보를 출력. `%{http_code}`는 **curl이 채워 주는 상태 코드**이고 사용자가 채울 값이 아님 |
| `curl -s -X POST http://<ALB-DNS>/ask -H "X-API-Key: $(aws ssm get-parameter ...)" -H "Content-Type: application/json" -d '{"question":"..."}'` | 키는 `$(...)`가 SSM에서 꺼내 바로 헤더에 넣음. **한 줄로** 입력(줄바꿈 `\`가 `-d`를 지운 적 있음) |

### 셸 규칙
- `*`, `?`, `[`가 들어간 인자는 **따옴표**로 감싼다(zsh가 파일 이름 패턴으로 해석해 `no matches found`가 난다). 예: `--filters "Name=group-name,Values=pharma-*"`.
- `export`가 없는 변수는 자식 프로세스(`aws`)에 전달되지 않는다.

---

## 6. 겪은 문제와 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| `aws sts get-caller-identity`가 `InvalidClientTokenId` | ① 환경변수에 옛 `AWS_ACCESS_KEY_ID`가 남아 SSO보다 우선 ② `~/.zshrc`에 `AWS_PROFILE=...`만 있고 **`export`가 없어** `aws`에 전달 안 됨(프롬프트는 셸 변수라 표시됨) | 옛 키 변수 해제, `export AWS_PROFILE=pharma-p5`를 `~/.zshrc`에 추가 |
| 프롬프트에 `AWS: pharma-p5`가 보이는데 실패 | 프롬프트 표시는 **로그인 상태가 아니라 변수 값**을 보여 줌 | `env \| grep ^AWS_`로 환경변수를 확인 |
| `docker version`에서 `Cannot connect to the Docker daemon` | Docker Desktop 엔진이 꺼져 있음 | Docker Desktop 실행 |
| `describe-security-groups`가 빈 결과 | 콘솔에서 **다른 리전**에 보안 그룹을 만듦 | 서울에서 다시 만들고 잘못 만든 것은 삭제. 이후 리전 확인 습관 |
| `no matches found: Name=group-name,Values=pharma-*` | zsh가 `*`를 파일 패턴으로 해석 | 인자 전체를 따옴표로 감쌈 |
| 태스크 정의에 태그를 빠뜨려 리비전 2 생성 | JSON의 `<TAG>` 칸을 채우지 않음(리비전은 수정이 아니라 쌓임) | 고쳐 등록. 리비전 1은 잘못된 상태로 남지만 실행되지 않음. 이후 JSON에는 태그를 미리 넣음 |
| `docker push`가 `the upload with id ... does not exist` | 업로드 세션이 도중에 끊김(큰 레이어, 네트워크). 원인 확정은 못 함 | 다시 push하자 성공(이미 올라간 레이어는 건너뜀) |
| Billing 화면 접근 거부(`AdministratorAccess`인데도) | IAM 사용자·역할의 결제 화면 접근은 기본 비활성 | 루트로 로그인해 "IAM user and role access to Billing information" 활성화 |
| 복원 이미지의 `COPY deploy/pharma.sql.gz`가 안 되는 문제를 사전에 발견(직접 확인) | 루트 `.dockerignore`에 `deploy`가 있음 | `deploy/`를 빌드 컨텍스트로 쓰고 `deploy/.dockerignore`(허용 목록) 추가 |
| 복원 시험에서 `pharma_ext` 쓰기 확인이 무효 | Claude가 없는 컬럼을 써서 권한 검사까지 가지 못함 | 올바른 구문으로 재시험해 거부 확인 |
| 다음 날 `/health` 시간 초과 | 맥북 공인 IP가 바뀌어 `pharma-alb-sg`의 허용 IP와 달라짐 | 규칙의 IP를 현재 값으로 수정(차단이 실제로 동작함을 확인한 사례이기도 함) |
| (연습) 서비스의 태스크가 헬스체크 실패로 교체됨, 타깃 상태 `unused` | 서비스 서브넷은 4개 AZ, ALB는 2개 AZ. ALB가 없는 AZ(2d)에 태스크가 놓임(추정) | 서비스 서브넷을 ALB와 같은 2a·2b로 줄여 다시 생성 |
| (연습) 타깃 그룹·서비스 이름이 틀림 | 입력 오타(`tg`→`sg`), 서비스 이름 칸은 기본값 그대로 | 이름은 바꿀 수 없어서 삭제 후 재생성. 입력 전 기본값 칸을 확인 |
| (연습) 다시 만든 타깃 그룹에 healthy 5·간격 30·지연 300이 남음 | 생성 마법사의 기본값(지연은 만든 뒤 Attributes에서 따로 설정) | 만든 뒤 조회로 값을 대조해 발견, 수정 |
| (연습) 이 PC·윈도우 브라우저에서 ALB 접속이 시간 초과 | `/32` 규칙이 ALB가 본 출발 IP와 맞지 않음(`checkip`의 IP와 다름, 원인 미확인) | 임시 `0.0.0.0/0`으로 규칙 문제임을 구분하고 바로 삭제. 이 네트워크에서는 `/32`를 신뢰하지 말 것 |
| (연습) `!`로 `aws configure sso` 실행이 실패 | 질문에 답할 터미널(TTY)이 없음 | 별도 WSL 터미널에서 실행 |
| (연습) AWS CLI 설치 스크립트가 권한 오류 | 압축 해제 방식(Python `zipfile`)이 실행 권한을 지움 | `chmod u+x`로 파일에 실행 권한을 주고 재설치 |
| (연습) SSO 프로파일이 `AdministratorAccess-<계정ID>`라는 기본 이름으로 저장됨 | `configure sso`의 기본값 | `~/.aws/config`의 프로파일 이름을 `pharma-lbtest`로 변경 |

---

## 7. 검증 상태

**확인한 것**
- 이미지가 비밀 없이 환경변수만으로 기동하고 amd64로 빌드된다(이 PC).
- 복원 스크립트의 로직, 중복 방지, 읽기 전용 역할(이 PC 임시 DB).
- RDS에서 복원 성공과 행 수 일치(사용자 보고).
- ECS 서비스가 ALB 뒤에서 healthy, `/health`·`/ready`·401·`/ask` 정답(사용자 보고).
- `/ready`의 DB 항목이 ok라는 것은 태스크 → RDS 네트워크 경로와 `sslmode=require` 접속이 통과했다는 뜻.
- 보안 그룹 IP 제한이 허용되지 않은 IP를 차단한다(맥북 IP 변경 시와 이 PC 요청의 시간 초과).
- CloudWatch 로그에 요청 ID가 붙은 JSON 로그가 찍힌다(사용자 보고).
- 철거: 8개 확인 명령이 모두 빈 결과(사용자 보고).
- (11-18 연습, 직접 확인) 서비스가 태스크 사설 IP를 타깃 그룹에 자동 등록하고 `describe-tasks`와 `describe-target-health`의 IP가 같다. 서비스에 저장되는 로드 밸런싱 값은 타깃 그룹·컨테이너 이름·포트 세 개. ALB와 AZ가 어긋난 태스크는 `unused`가 되어 헬스체크 실패로 교체된다. 보안 그룹 `/32` 규칙이 접속 여부를 갈랐다(§4-N).
- (11-18, 직접 확인) 이 PC에서 AWS 조회가 된다(SSO, `pharma-lbtest`).

**미검증**
- 이 회사 네트워크에서 ALB가 본 출발 IP가 `checkip`의 값과 다른 이유(§4-N-5).
- ALB 생성 직후 서비스 없이 503이 나오는지, nginx 응답 본문(§4-N).
- 서킷 브레이커의 **자동 롤백이 실제로 동작하는지**(첫 배포라 되돌릴 리비전이 없었음. 8단계에서 일부러 나쁜 리비전을 배포해 확인할 예정).
- 서버 인증서 검증(`verify-full`)은 하지 않았다. `sslmode=require`는 암호화만 보장한다.
- 이번 응답에서 모델이 어떤 도구를 몇 번 호출했는지(응답 본문과 로그의 상세는 확인하지 않음).
- 서울 리전의 ALB·Fargate·공인 IPv4 요금(웹 검색에서 확인되지 않음, RDS 견적만 콘솔로 확인).

**한계**
- **HTTP 평문**: 요청 본문과 API 키가 암호화되지 않고 오간다. 도메인이 없어 HTTPS 인증서를 쓰지 못했다.
- **태스크가 공인 IP를 가짐**: NAT Gateway(비쌈)를 쓰지 않고 공용 서브넷에 두었다. 들어오는 쪽은 보안 그룹이 ALB만 허용하지만, 현업은 비공개 서브넷 + NAT 또는 VPC 엔드포인트를 쓰는 경우가 많다.
- **복원 태스크가 앱과 같은 실행 역할을 공유**하고 그 역할은 `/pharma/*`를 읽을 수 있다. 앱 태스크 정의는 관리자 비밀번호를 연결하지 않아 실제로는 읽지 않지만, 현업이면 역할이나 경로를 나눈다.
- 단일 AZ RDS, 태스크 1개: 가용성은 고려하지 않은 학습용 구성이다.
- 콘솔로 만들어 **Terraform에 기록이 없다**(다음 작업에서 코드로 옮김).
- ALB 허용 IP가 맥북 한 대의 현재 IP라 네트워크가 바뀌면 다시 고쳐야 한다. 회사 네트워크(이 PC)에서는 `/32`가 통과하지 않는 것도 확인됐다(§4-N-5).
- 11-17까지 앱 배포의 AWS 실행은 맥북 기준이었다. 11-18부터 이 PC에서도 AWS를 쓸 수 있다.

---

## 8. 비용과 철거

- 사전 추정은 `docs/ecs_cost_and_teardown.md`(시간당 상한 약 $0.13, RDS 견적 월 $20.87).
- **실측**: 켜 둔 시간, Billing 사용액은 **미기록**(사용자가 Billing 화면에서 확인해 해당 문서의 "실측" 칸에 적을 예정).
- **철거**(사용자 보고): 안내한 순서(ECS 서비스 → ALB·타깃 그룹 → RDS(최종 스냅샷·자동 백업 보존 없이) → ECR 저장소 → 로그 그룹 → 클러스터 → 보안 그룹)로 진행했고 "철거 완료"라고 보고했다. **확인된 것은 아래 8개 명령이 모두 빈 결과라는 것뿐이다**: `ecs list-clusters`, `elbv2 describe-load-balancers`, `rds describe-db-instances`, `rds describe-db-snapshots`, `ecr describe-repositories`, `logs describe-log-groups`, `ec2 describe-addresses`, `ec2 describe-network-interfaces`.
- **11-17에 미확인이던 항목을 11-18에 직접 조회로 확인**: 타깃 그룹 **없음**, RDS 자동 백업 보존분 **없음**, ECS 클러스터 **없음**. 보안 그룹 `pharma-task-sg`·`pharma-rds-sg`·`pharma-alb-sg` **3개는 남아 있다**(과금 없음). Terraform이 같은 이름으로 만들면 충돌하므로 그 전에 지우거나 가져오기(import)로 정해야 한다.
- 11-18 연습(`lbtest-*`)의 철거 확인은 §4-N. 활성 태스크 정의 4개(`lbtest-nginx:1`, `pharma-restore:1`, `pharma-scm-agent:2·3`)는 과금이 없어 남겨 두었다.
- **남겨 둔 것**: SSM 파라미터 7개, IAM 역할 `pharma-ecs-execution`, 6단계 역할과 파라미터(과금 없음). Anthropic 서버용 키는 SSM에 있는 그대로다.

---

## 9. 복습 질문 (답을 못 하면 위 절로)

1. 서버에 SSH로 들어가던 지난 방식과 이번 방식(ECS + Fargate)의 가장 큰 차이는? DB를 컨테이너 밖(RDS)에 둔 이유는? (§1, §2)
2. 이미지, 컨테이너, 태스크 정의, 태스크, 서비스의 관계를 프리팹·인스턴스·풀 매니저로 설명해 보라. (§2)
3. 태스크 정의에서 수정이 아니라 리비전이 쌓이는 이유와, 그것이 롤백에 주는 이점은? (§2, §4-F)
4. `/ask` 한 번이 맥북에서 시작해 다시 맥북으로 돌아오기까지 거치는 곳을 순서대로. 중간에 보안 그룹이 어디서 무엇을 막는가? (§3)
5. 비밀(API 키, DB 비밀번호)은 어디에 저장되고, 누가, 언제 컨테이너에 넣어 주는가? 이미지에는 왜 비밀이 없는가? (§3)
6. 타깃 그룹의 헬스체크는 왜 `/ready`가 아니라 `/health`인가? (§2)
7. `export`가 없을 때 `aws`가 프로필을 모르는 이유는? (§5, §6)
8. RDS가 `available`이 되어도 맥북에서 바로 접속할 수 없는 이유와, 그래서 데이터를 넣은 방법은? (§4-J)
9. 이번에 "확인했다"고 쓸 수 있는 것과 "미검증"으로 남긴 것의 차이를 말해 보라. 자동 롤백은 어느 쪽인가? (§7)
10. 타깃 그룹을 만들 때 서버 정보를 하나도 넣지 않았는데 ALB가 어떻게 서버로 요청을 보내는가? 서비스의 로드 밸런싱 설정에 실제로 저장되는 값 세 가지는? (§4-N)
11. ALB와 서비스의 서브넷 AZ가 어긋나면 무슨 일이 생기고 어떻게 알아챌 수 있는가? (§4-N-3)
12. 보안 그룹에 내 IP `/32`를 넣었는데 접속이 안 될 때, 규칙 문제인지 방화벽 문제인지 가르는 방법과 이번 결론은? (§4-N-5)

---

## 10. 다음 작업
1. 이 콘솔 구성을 **Terraform 코드로 옮긴다**(같은 구성을 코드로 다시 만들며 검증). IAM은 `AdministratorAccess` 프로필이 필요하다. 코드에 반영할 점: 서비스 서브넷을 ALB의 AZ와 일치시키기, 타깃 그룹 기본값(healthy·간격·등록 해제 지연) 명시, 앱 서비스는 헬스체크 유예 60초, 남은 `pharma-*` 보안 그룹 3개의 처리(삭제 또는 import), **허용 IP를 어떻게 둘지**(§4-N-5).
2. **8단계 CD**: GitHub Actions + OIDC → ECR push(태그 git sha) → ECS 배포, 평가 게이트 연결, 일부러 나쁜 리비전을 배포해 **자동 롤백 확인**.
3. 비용 실측 기록.
