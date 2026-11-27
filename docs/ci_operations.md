# CI 운영 규칙 (2026-11-12)

평가 게이트의 규칙과 임계치는 `docs/eval_protocol.md`의 "CI 게이트" 절, 임계치의 근거는 `docs/eval_repeat_variance_results.md`에 있다. 이 문서는 **CI를 어떻게 운영하는가**만 적는다.

## 워크플로 파일
| 워크플로 | 언제 도나 | 무엇을 하나 | LLM 호출 |
|---|---|---|---|
| `ci.yml` | 모든 push, 모든 PR | `test`(ruff, pytest 111개, Postgres 복원 포함, 재사용 워크플로 `_checks.yml`을 `run_tests`로 호출), `docker`(이미지 빌드만) | 없음 |
| `eval-smoke.yml` | **PR에서** 아래 경로가 바뀔 때 | `_checks.yml`을 `run_smoke`로 호출: 스모크 6문항 실행 → 집계 → 게이트 판정 | 약 10회, 입력 약 2.5만 토큰 |
| `eval-full.yml` | **수동**(`workflow_dispatch`) | 114문항 전체 실행, 집계, 결과 30일 보관. 게이트는 적용하지 않음 | 약 225회, 입력 약 58.7만 토큰 |
| `deploy.yml` | master push(`src/**`, `pyproject.toml`, `uv.lock`, `Dockerfile` 변경, 저장소 변수 `DEPLOY_ENABLED`가 `true`일 때만)와 수동(`approve_cost`) | `gate`(`_checks.yml`을 `run_tests`·`run_smoke`로 호출) 통과 뒤 ECR push와 ECS 배포 | 게이트가 약 10회 |
| `_checks.yml` | 직접 실행되지 않음(`workflow_call`) | 환경 준비(Postgres, uv, 의존성, DB 복원)와 린트·테스트·스모크 평가·게이트 판정을 입력(`run_tests`, `run_smoke`, `run_prefix`)에 따라 실행 | `run_smoke`일 때만 |

`deploy.yml`의 배포 단계(OIDC, ECR, ECS)의 동작은 워크플로 파일의 주석과 `docs/interview_concepts.md` 10~12절(OIDC, 서킷 브레이커 롤백, Terraform과 CD의 역할 분담)을 본다. 실행 기록은 아래 "검증 상태 추가 (2026-11-27, 공개 저장소)"에 있다.

`eval-smoke`의 경로 필터: `src/pharma_scm/agent/**`, `src/pharma_scm/evalset/**`, `eval/**`, `scripts/ci_restore_db.sh`, `deploy/pharma.sql.gz`, `pyproject.toml`, `uv.lock`, 워크플로 파일 자체. 이 밖(문서, 테스트, API 서버 코드 등)만 바뀐 PR에서는 돌지 않는다.
같은 PR에 커밋을 더 올리면 진행 중인 스모크는 취소되고 새로 돈다(불필요한 호출 방지). 전체 평가는 동시에 둘이 돌지 않으며 진행 중인 것은 취소하지 않는다.

## 비밀 값
- `ANTHROPIC_API_KEY`는 저장소 Secrets에 등록되어 있다(Settings → Secrets and variables → Actions). 값은 로그에 `***`로 가려진다.
- 키를 바꾸면 같은 이름으로 다시 등록한다. 키를 코드·문서·artifact에 넣지 않는다.
- **fork에서 온 PR에는 시크릿이 전달되지 않는다.** 그래서 `eval-smoke`는 fork PR이면 실행하지 않도록 조건(`head.repo.full_name == github.repository`)을 걸었다. 실패가 아니라 **건너뜀**으로 표시되므로, fork PR은 스모크 판정 없이 머지하지 않는다(메인테이너가 로컬에서 같은 명령으로 돌려 확인한다). 이 저장소는 현재 비공개이고 fork가 없다.

## 머지 규칙 (branch protection을 쓸 수 없다)
이 저장소는 개인 계정의 **무료 플랜 비공개** 저장소라 branch protection·rulesets를 설정할 수 없다(API가 "Upgrade to GitHub Pro or make this repository public"으로 응답, 2026-11-12와 2026-11-25 확인). 그래서 체크가 실패해도 **머지 버튼이 막히지 않는다.** 혼자 쓰는 저장소이고, **`master`에서 바로 작업하는 것이 현재 규칙이다**(2026-11-12 합의). PR은 PR 이벤트에서만 도는 검사를 확인해야 할 때만 쓴다. 사람이 아래를 지킨다.
1. `master`에 push한 뒤 `ci`의 `test`와 `docker`가 성공했는지 확인한다. 실패하면 다음 작업 전에 고친다.
2. **에이전트·평가 관련 경로**(아래 경로 필터)를 바꿀 때는 PR을 만들어 `eval-smoke`가 **성공(게이트 통과)** 한 뒤 합친다. 이 검사는 PR 이벤트에서만 돌기 때문이다. 실패하면 합치지 않고 아래 "스모크가 실패했을 때"로 원인을 본다. 재사용 워크플로로 바꿀 때도 이렇게 확인했다(PR #3).
3. `eval-smoke`가 돌지 않는 변경(경로 필터 밖)은 에이전트 동작이 바뀌지 않은 것으로 본다. 판단이 애매하면 PR을 만들어 강제로 돌리거나 로컬에서 같은 명령을 돌린다.
- 이 규칙은 사람의 약속이며 강제되지 않는다. 팀 협업이나 Pro 이상으로 바뀌면 `test`, `smoke`를 필수 체크로 지정하고 `eval/baseline.json`을 `CODEOWNERS`로 보호한다(코드 오너 리뷰 강제도 같은 기능이 필요하다).

## 스모크가 실패했을 때
1. PR의 Checks → `eval-smoke` → `smoke / checks` job → 실패한 단계의 로그를 연다. 터미널: `gh run view <실행 ID> --log`.
2. 어느 단계에서 실패했는지로 원인을 가른다.
   | 실패한 단계 | 의미 |
   |---|---|
   | 스모크 평가 실행 | 문항이 예외로 실패했다(`--strict`). API 키·네트워크·모델 접근 문제일 수 있다 |
   | 게이트 판정 | `게이트 실패 (N건)` 아래에 사유가 나온다(안전, 정답률, 형식, 토큰·호출) |
   | DB 복원 | 덤프 또는 Postgres 서비스 문제. 행 수가 기대값과 다르면 이 단계에서 멈춘다 |
3. 문항별 상세(답변, 도구 호출, 채점 사유)는 실행 페이지 맨 아래 **Artifacts**의 `smoke-<커밋 해시>`(14일 보관)를 받아 본다. 터미널: `gh run download <실행 ID> -n smoke-<해시> -D <새 폴더>`.
4. 흔들림 때문에 한 번 실패한 것인지 구분하려면 같은 커밋으로 다시 돌린다(Actions의 Re-run). 다시 돌려도 같은 문항이 실패하면 변경 때문일 가능성이 높다. **재실행을 거듭해 통과할 때까지 돌리지 않는다**(규칙을 우회하는 것이다). 우연한 실패가 반복되면 임계치를 낮추지 말고 새 반복 측정으로 근거를 만든다.

## 전체 평가(`eval-full`) 실행 절차
- **비용 승인이 먼저다.** 실행 입력의 `approve_cost`를 체크해야만 돈다. 입력란에 호출 수와 토큰(약 225회, 입력 약 58.7만)이 적혀 있다. 승인은 이 호출량을 인지하고 누르는 것이다.
- 실행하는 곳: Actions 탭 → `eval-full` → Run workflow. 수동 실행 버튼은 이 파일이 **기본 브랜치(`master`)에 있어야 보인다**(GitHub의 알려진 동작. 웹의 버튼 화면은 직접 확인하지 못했고, 같은 요청을 `gh workflow run eval-full.yml --ref master -f approve_cost=true`로 보내 실행을 확인했다).
- 결과: 실행 페이지의 Job Summary에 집계가 표시되고, `full-<커밋 해시>` artifact(30일 보관)에 문항별 결과와 `summary.json`이 들어 있다.
- 게이트는 적용하지 않는다. `baseline.json`의 임계치가 스모크 6문항용이라 전체(v1은 111/114)에 쓰면 항상 실패하기 때문이다.

## `eval/baseline.json`을 바꾸는 절차
다음 중 하나가 바뀔 때만 바꾼다: 프롬프트(`PROMPT_VERSION` 상승), 평가 문항, 모델, 채점기.
1. 새 버전으로 `eval-full`을 실행해 전체 결과를 얻는다(승인 필요).
2. 임계치를 바꿀 근거가 필요하면 새 반복 측정을 **사전 등록 후** 실행한다(`docs/eval_repeat_variance.md` 형식). 스모크 한 번의 통과·실패로 임계치를 조정하지 않는다.
3. `eval/registered.json`(문항 md5, 버전, 프롬프트 해시)과 `eval/baseline.json`(새 전체 집계와 임계치)을 한 PR에서 같이 바꾸고, PR 본문에 전체 평가 실행 링크와 근거 문서를 붙인다.
4. **자동으로 갱신하지 않는다.** CI가 baseline을 스스로 덮어쓰는 단계를 만들지 않는다.

## 로컬에서 같은 검사를 돌리는 법
```bash
docker compose up -d db                      # DB(5433). 꺼져 있으면 DB 테스트가 실패가 아니라 skip된다
uv run ruff check . && uv run pytest -q      # skip이 0인지 본다(111 passed)
# 스모크(LLM 호출, 승인 후)
uv run python -m pharma_scm.evalset.run_eval --run-id smoke_local --ids "$(cat eval/smoke_ids.txt)" --strict
uv run python -m pharma_scm.evalset.report smoke_local --json data/runs/smoke_local/summary.json
uv run python -m pharma_scm.evalset.gate data/runs/smoke_local/summary.json
```
`data/runs/`는 git 밖이다. 같은 `--run-id`로 다시 돌리면 이미 있는 결과를 건너뛰므로, 프롬프트를 고쳤다면 새 `--run-id`를 쓴다.

## 검증 상태 (2026-11-12)
- 검증됨: `ci`(Postgres 복원 포함 111 passed, skip 0), `eval-smoke`의 **통과 경로**(PR #1, 6문항 PASS, 게이트 통과, artifact 6,007B 보관, 사용량 호출 10회·입력 25,382토큰).
- 검증됨(2026-11-12): **`eval-full`**. 실행 `43171436991`(`master` `fd930ea`, `approve_cost=true`)이 성공했다. 114문항, 실행 오류 0건, 전체 112/114(A 43/44, B·C·D 전부, E 14/15), 형식 113/114, 안전 위반 0건, LLM 호출 225회·입력 586,616/출력 33,157토큰, artifact `full-fd930ea…` 109,462B(2026-12-12까지 보관). 로컬 `main_v1`(111/114, 입력 586,865)과 거의 같고, 로컬에서 실패했던 E010이 이번엔 통과했다(모델 비결정성의 사례). 실패는 A037(숫자 54.1≠54.6)과 E009(`최종 답:` 줄 없음).
- 미검증: `eval-smoke`의 **실패 경로**(게이트가 실제 Actions에서 job을 실패시키는 것, 단위 테스트로만 확인), fork PR 스킵 조건, 웹의 "Run workflow" 버튼 화면.

## 검증 상태 추가 (2026-11-25)
- **원인 확인(직접 확인)**: 2026-11-23~24의 `ci` 실패 4건(ea13c2a, d631f12, 9453caa, e70bf8d)은 로그 4건이 모두 `scripts/ci_restore_db.sh: Permission denied`(종료 코드 126)였다. git에 `100644`(실행 비트 없음)로 커밋돼 있었기 때문이고, `100755`로 커밋한 뒤(`fa9068f`) `ci`가 성공으로 돌아왔다. 이 PC에서는 파일이 실행 가능해 몰랐다.
- 검증됨: 재사용 워크플로 `_checks.yml`을 쓰는 `ci`(`run_tests`, 스모크 단계는 건너뜀)와 `eval-smoke`(PR #3, `run_smoke`, 게이트 판정 통과, artifact `smoke-<해시>` 이름 유지).
- 미검증: `deploy.yml`의 `gate`가 두 입력을 함께 넘기는 실제 실행(인프라가 내려가 있어 실행하지 않았다, 다음 배포 때 처음 돈다), `DEPLOY_ENABLED=true`로 켠 push 배포, 위 "미검증"의 나머지 항목.

## 검증 상태 추가 (2026-11-27, 공개 저장소)
- 검증됨: **`deploy.yml` 수동 실행의 전 과정**. 실행 `45911908033`(`master` `6bcda11`, `approve_cost=true`)이 성공했다. `gate`(재사용 `_checks.yml`에 `run_tests`·`run_smoke`를 함께 넘김: pytest 149 passed·2 skipped, 스모크 평가와 게이트 판정 통과, 약 2분) → `deploy`(OIDC 역할 맡기, 이미지 빌드·ECR push, 새 태스크 정의 등록, 서비스 교체, 약 7분 반). ECS 서비스가 리비전 9(이미지 `boot-6bcda11`) → 10(`6bcda11`)으로 바뀌어 `COMPLETED`·steady state가 됐고, ALB 경유 `/health`·`/ready` 200, 키 없는 `/ask` 401, `/ask` 1회 정답(`query_db`, 90)을 확인했다. 새 저장소의 숫자 ID로 바꾼 OIDC 신뢰 정책(`825d46c`)으로 역할 맡기가 통과한 것도 이 실행이 처음이다.
- 순서: 스택을 Terraform으로 올릴 때 서비스가 쓸 첫 이미지를 `boot-<해시>` 태그로 직접 push했다. ECR 태그가 불변이라, 같은 커밋을 Actions가 `<해시>` 태그로 push할 수 있게 하려는 것이다. 이후 배포는 Actions만 했다.
- 경고: `actions/checkout@v4`, `aws-actions/configure-aws-credentials@v4`가 Node.js 20 대상이라 Node.js 24로 강제 실행된다는 경고가 나왔다(이번 실행에는 영향 없음).
- 인프라는 실행 뒤 철거했다(비용은 `docs/ecs_cost_and_teardown.md` §5).
- 미검증(그대로): `DEPLOY_ENABLED=true`로 켠 push 배포, 앱이 뜬 뒤 헬스 체크에 실패하는 경우의 롤백, 수동 롤백, 서킷 브레이커 실패 임계값, `eval-smoke` 실패 경로, fork PR 스킵.
