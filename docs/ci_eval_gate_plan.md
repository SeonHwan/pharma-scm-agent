# CI 평가 게이트 구현 계획 (새 세션 시작용)

> **상태(2026-11-25): 설계 기록이다.** 과제 1~6은 모두 완료됐다. 현재 상태와 운영은 `docs/ci_eval_gate_handoff.md`, `docs/ci_operations.md`를 본다. 아래의 "아직 아무 코드도 바꾸지 않았다" 같은 서술은 작성 시점(2026-11-10)의 것이라 그대로 둔다.

이 문서만 읽고 바로 시작할 수 있게 쓴 인계 문서다. 작성 2026-11-10, 브랜치 `learn/ci-cd`. **아직 아무 코드도 바꾸지 않았다.** 이 문서가 시작점이다.

## 목표
평가 시스템(`src/pharma_scm/evalset/`)을 GitHub Actions에 연결해, **프롬프트·도구·그래프·채점기를 바꾼 PR이 정답률·안전·비용 회귀를 만들면 머지를 막는다.** 배포 자동화(ECR/ECS)는 범위 밖.

## 사용자 작업 규칙 (반드시 지킬 것)
- 커밋·push는 사용자가 요청할 때만. 작업 단위마다 "커밋할까요"를 묻는다.
- **LLM을 실제로 호출하는 작업은 호출 수·토큰·비용을 먼저 계산해 보여주고 승인받은 뒤 실행**한다(과제 4, 6).
- 이 PC에서 AWS 명령은 인증서 문제로 실패한다. 이번 과제는 AWS를 쓰지 않는다.
- 검증하지 않은 것은 "미검증"이라고 적는다. YAML은 실제 Actions에서 돌려 보기 전까지 미검증이다(사용자가 push해서 확인).
- 사용자는 Unity/C# 개발자, 서버·CI가 처음이다. 설명은 "평가 절차(재료 고정→실행→채점→집계→판정→보관→연결)" 순서로, 파일 위에서 아래로 읽는 방식은 피한다.
- 대명사를 모르면 they/them. 타입 힌트는 쓰지 않는다(저장소 스타일). 주석은 한국어, 기존 밀도에 맞춘다.
- 작업 파일: `data/raw/*` 3개와 `openfda_result.txt`의 공백 변경은 **의도적으로 커밋하지 않는 것**이다. `git add -A` 금지, 파일을 지정해서 add.

## 현재 상태 (코드에서 확인한 사실)
평가 파이프라인 7막과 코드 위치:

| 막 | 있음? | 위치 |
|---|---|---|
| ① 재료 고정 | 있음(비교 코드는 없음) | `eval/questions.jsonl`(114문항), `agent/prompt.py:5` `PROMPT_VERSION="v1"`, `:48` `PROMPT_SHA`, 등록값은 `docs/eval_protocol.md:6`에 **문서로만** |
| ② 실행 | 있음 | `evalset/run_eval.py` `main()`(:45), `run_one()`(:28) |
| ③ 채점 | 있음 | `evalset/grader.py`(`run_one` 안 `:39`에서 호출). 규칙 코드, LLM 아님 |
| ④ 집계 | 있음(출력만) | `evalset/report.py` `main(run_id)`. **print만 하고 파일 저장·종료코드 없음** |
| ⑤ 판정 | **없음** | 만들어야 함 |
| ⑥ 보관 | 로컬만 | `data/runs/<run_id>/`(`.gitignore`의 `/data/`) |
| ⑦ 연결 | **없음** | `.github/workflows/ci.yml`은 `test`(ruff+pytest)와 `docker`(빌드만) |

알아 둘 동작:
- `run_eval`: 기본 `run_id=main_{PROMPT_VERSION}`, 결과 파일이 이미 있는 문항은 **건너뜀**, `_meta.json`은 **없을 때만** 기록, 항상 종료코드 0, `--ids` 없음, `--dry-run`은 API 호출 없이 계획만 출력.
- 위 때문에 프롬프트를 고치고 같은 `run_id`로 돌리면 옛 결과가 재사용된다. CI에서는 `run_id`에 커밋 sha를 넣어야 한다.
- 도구 결과는 2000자로 잘려 저장된다. 문항 결과에는 도구 호출 내용과 답변이 들어간다.
- 에이전트 도구는 **실제 Postgres**를 친다(`config.py`의 `PHARMA_ADMIN_DSN`/`PHARMA_RO_DSN`/`PHARMA_EXT_DSN`, 기본 `localhost:5433`, 비밀번호 `local-dev-only`). 그래서 스모크도 DB가 필요하다.
- DB 테스트는 `tests/conftest.py`의 `needs_db` 픽스처로, Postgres에 접속 못하면 건너뛴다. 현재 CI는 DB가 없어서 `tests/test_tools.py`의 4개(`returns_rows`, `truncates_at_200_rows`, `get_shortage_current`, `get_shortage_no_record`)가 항상 skip.
- 로컬 DB: `compose.yaml`(postgres:17, 사용자 `pharma_admin`, DB `pharma`, 포트 5433). 덤프는 `deploy/pharma.sql.gz`(git 추적). 덤프에는 `GRANT ... TO pharma_ro/pharma_ext`가 있어서 **복원 전에 두 역할을 먼저 만들어야** 한다. `deploy/restore_db.sh`는 `docker compose exec`를 써서 CI 서비스 컨테이너에 그대로 못 쓴다(역할 생성 SQL과 `ALTER ROLE` 설정은 참고해서 CI용으로 다시 쓴다).
- 복원 후 기대 행 수: products 90, sales_orders 180519, inventory_lots 228, shortage_events 1622, sop_sections 30.
- 문항 구성: A44 B20 C20 D15 E15 (`gold.kind`: number 51, sections 20, status 16, refusal 15, status_number 10, set 2). **`gold_sql`은 A 44개에만 있다.**
- 비용 실측(v1 전체): 225회 호출, 입력 586,865 / 출력 32,123 토큰. 스모크 5문항: 호출 9회, 입력 23,777 / 출력 1,242. repeat-variance(30×5) 추정 약 120만 토큰.
- 모델 `claude-sonnet-5-5`는 temperature를 바꿀 수 없다 → 비결정적. 그래서 임계치는 반복 측정 뒤에 정한다.
- 기존 CI 테스트 36개. `tests/test_grader.py`는 "정답 문장 전부 통과 / 망가뜨린 답 전부 실패"를 이미 검증한다.

## 과제 1~6 (순서대로)

### 1. CI에 Postgres 서비스 + 덤프 복원 → 건너뛰던 DB 테스트 실행 (비용 0)
- `ci.yml`의 `test` job에 `services: postgres`(postgres:17, `POSTGRES_USER=pharma_admin`, `POSTGRES_DB=pharma`, 비밀번호 `local-dev-only`, 헬스체크 옵션, 포트 `5433:5432`로 두면 `config.py` 기본값이 그대로 맞다).
- pytest 전에 스텝 추가: 역할 `pharma_ro`/`pharma_ext` 생성 → `gunzip -c deploy/pharma.sql.gz | psql` → `ALTER ROLE ... default_transaction_read_only=on, statement_timeout='5s'`(restore_db.sh의 3단계와 같게). 행 수 확인 스텝도 둔다.
- 이 스크립트는 `deploy/`가 아니라 CI 전용 파일(예: `scripts/ci_restore_db.sh`)로 만들고 `psql` 접속은 `PGPASSWORD` 환경변수 방식으로 한다.
- 완료 기준: pytest가 36 passed(skip 0)로 끝난다. 로컬에서는 `docker compose up -d db` 후 `uv run pytest -q`로 같은 환경을 재현해 본다.

### 2. `gold_sql` ↔ `gold` 일치 테스트 (비용 0, 1번 선행)
- 새 테스트(예: `tests/test_evalset_gold.py`, `needs_db` 사용): A 44문항의 `gold_sql`을 **읽기 전용 계정(RO_DSN)** 으로 실행해 결과가 `gold.value`와 같은지 확인(정수 일치, 소수는 채점기와 같은 ±0.05 규칙 — `grader.py`의 `_num_ok` 재사용).
- 이유: 정답표가 DB와 어긋나면 에이전트가 맞아도 오답이 된다. `docs/eval_protocol.md`에 "gold_sql을 재실행해 같은 값을 확인했다"고 적혀 있으나 **테스트로 고정돼 있지 않다.**

### 3. 문항 md5·프롬프트 해시 등록값 비교 (비용 0, 독립)
- 등록값을 **코드가 읽을 수 있는 git 파일**에 둔다. 제안: `eval/registered.json` = `{"questions_md5": "e96780f475db1108c1e3a4eb35a2fe67", "prompt_version": "v1", "prompt_sha": "b92313567d93"}`.
- 테스트(예: `tests/test_eval_registration.py`)가 현재 `eval/questions.jsonl`의 md5, `PROMPT_VERSION`, `PROMPT_SHA`가 등록값과 같은지 비교. 다르면 실패 — 메시지에 "의도한 변경이면 버전을 올리고 registered.json과 baseline을 PR로 갱신"을 안내.
- 현재 md5는 `docs/eval_protocol.md`, `docs/eval_results_v1.md`, 그리고 이 PC의 `data/runs/main_v1/_meta.json`(git 밖)에만 있다. 이 과제로 처음 코드가 읽는 위치가 생긴다.
- 주의: 프롬프트 sha가 지금 값(`b92313567d93`)과 같은지 먼저 계산해서 확인한 뒤 등록한다.

### 4. repeat-variance 측정 (LLM 호출, **승인 필요**)
- 목적: 같은 조건 반복에서 정답률·토큰이 얼마나 흔들리는지 재서 **스모크 임계치의 근거**를 만든다.
- 설계 초안(사용자와 확정할 것): 문항 30개 × 5회 ≈ 150문항 실행 ≈ 입력 120만 토큰. 문항 선택은 5유형 층화(예: 유형당 6개), 고정 목록을 파일로 남긴다. 호출 수·토큰·비용을 `--dry-run`식으로 먼저 계산해 보여주고 승인받는다.
- 이 과제는 5번의 `--ids`와 `run_id` 옵션이 있으면 편하다. 순서를 바꿔 5번의 `run_eval` 변경(`--ids`, `run_id`)을 먼저 해도 된다.
- 결과로 얻을 것: 문항별·유형별 통과율의 분산, 문항당 토큰의 변동폭. 이것을 `docs/`에 사전 등록 방식으로 기록한다(결과를 보고 규칙을 바꾸지 않는다).

### 5. `run_eval` 확장 + `gate.py` + `baseline.json` (비용 0, 임계치는 4번 이후)
- `run_eval.py`: `--ids A001,B001,...`(또는 파일), 기본 `run_id`에 선택적으로 커밋 sha, 문항 실행 중 오류·형식 위반 요약 후 종료코드(스모크용). 기존 동작(기본값)은 바꾸지 않는다.
- `report.py`: 같은 집계를 **JSON으로도 출력**(예: `--json 경로`). 집계 로직은 중복 구현하지 말고 함수로 분리해서 print 버전과 JSON 버전이 공유한다.
- `evalset/gate.py`: 실행 결과(JSON 집계)와 `eval/baseline.json`을 비교해 규칙대로 판정하고 **실패 시 종료코드 1**과 사유를 출력한다. 규칙:
  - 안전 검사 위반(E에서 쓰기·시스템 SQL 시도) 1건이면 즉시 실패
  - 형식 준수율이 기준선보다 낮으면 실패
  - 유형별 정답률이 기준선 허용 하한 아래면 실패(하한은 4번 결과로 정함)
  - 토큰·호출 수가 기준선의 일정 배수를 넘으면 실패 또는 승인 요구
  - 평가 재료 해시 불일치(3번)는 별도 테스트로 이미 걸림
- `eval/baseline.json`: v1 전체 실행 요약(`docs/eval_results_v1.md`, `data/runs/main_v1`에서 `report`로 재집계)을 기준선으로 고정. **자동 갱신 금지**, 갱신은 PR로 사람이 하고 전체 평가 결과를 근거로 첨부한다. `CODEOWNERS`로 보호.
- 게이트 로직 자체는 **가짜 결과 JSON으로 단위 테스트**(비용 0): 위반 1건이면 실패, 기준선 이내면 통과, 토큰 2배면 실패 등.

### 6. 스모크 워크플로 + 수동 전체 평가 워크플로 (LLM 호출, **승인 필요**)
- 스모크: `paths:` 필터(`agent/prompt.py`, `agent/graph.py`, `agent/tools*`, `evalset/**`, `eval/**` 등 실제 파일명을 `ls`로 확인해서 지정). Postgres 서비스 + 덤프 복원(1번 스텝 재사용) → 고정된 5~6문항(**E 최소 1~2개 포함**) 실행 → `gate.py`. `ANTHROPIC_API_KEY`는 GitHub Secrets(미등록 상태면 사용자에게 등록 요청). **fork PR에서는 시크릿이 없어 스킵**되는 점을 문서화.
- 수동 전체 평가(`workflow_dispatch`): 114문항, `run_id`에 sha, 결과 `data/runs/<run_id>/`와 집계 JSON을 `upload-artifact`(보관 기간 지정). 비용 약 58.7만 입력 토큰이므로 실행 전 승인 절차를 문서에 적는다.
- branch protection(필수 체크 지정)은 저장소 설정이라 **사용자가 GitHub에서 직접** 해야 한다 — 방법을 안내만 한다.
- 둘 다 실제 Actions에서 돌려 보기 전까지 **미검증**으로 표기.

## 권장 진행 순서
1 → 2 → 3(독립, 아무 때나) → 5의 코드 부분(`--ids`, `report --json`, `gate.py` + 단위 테스트) → 4(승인 후 측정, 5의 옵션 사용) → 임계치 확정·`baseline.json` → 6.
(문서의 번호 순서와 다르지만, 4번이 5번의 `--ids`를 쓰고 5번의 임계치가 4번에 의존하므로 이 순서가 막힘이 없다.)

## 완료 후 갱신할 문서
- `docs/eval_protocol.md`에 게이트 규칙·임계치(사전 등록 방식, 측정 결과 링크)
- `HANDOFF.md`에 이 작업의 상태 한 줄

## 첫 행동 제안
1. `git status`로 현재 상태를 확인하고(`data/raw/*`·`openfda_result.txt`는 건드리지 않는다), 로컬에서 `docker compose up -d db` + 덤프 복원 후 `uv run pytest -q`가 36 passed인지 확인한다(DB 컨테이너가 이미 있으면 상태만 확인).
2. 과제 1부터 시작한다. 작업 전에 사용자에게 어디까지 한 번에 할지(1~3 묶음 등) 묻는다.
