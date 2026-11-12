# 과제 1 검증 절차: CI에서 DB 테스트 실행 (개인 PC용)

`docs/ci_eval_gate_plan.md`의 과제 1 결과를 다른 PC에서 직접 확인하는 절차다.
목표: 건너뛰던 DB 테스트 4개(`tests/test_tools.py`)가 실행되어 **36 passed, skip 0**이 된다.

## 용어
- **호스트**: 컨테이너를 돌리는 머신. 아래 1~3단계에서는 개인 PC, 4단계에서는 GitHub 러너.
- **Compose 서비스 `db`**: `compose.yaml`에 정의된 Postgres. `docker compose` 명령으로 다룬다.
- **Actions 서비스 컨테이너**: `ci.yml`의 `services:`로 Actions가 만드는 Postgres. Compose와 무관하다.

## 준비물
- Docker (Compose 포함), git, uv, 이 저장소의 `learn/ci-cd` 브랜치

```bash
git clone <저장소 URL> pharma-scm-agent && cd pharma-scm-agent
git checkout learn/ci-cd
uv sync --frozen
```

## 1단계: DB가 없을 때 4개가 skip되는지 확인 (CI 수정 전 상태 재현)
`localhost:5433`에 아무것도 떠 있지 않아야 한다(`docker ps`로 확인).

```bash
uv run pytest -q -rs
```
기대: `32 passed, 4 skipped` (skip 사유 `Postgres 없음`, `tests/test_tools.py`의 4곳).

## 2단계: 복원 스크립트를 빈 DB에서 확인
호스트에 `psql`이 없어도 되도록, 임시 Postgres와 스크립트 실행 모두 컨테이너로 한다. 포트는 로컬 DB와 겹치지 않게 5434를 쓴다.

```bash
docker run -d --rm --name ci-pg-test \
  -e POSTGRES_USER=pharma_admin -e POSTGRES_PASSWORD=local-dev-only -e POSTGRES_DB=pharma \
  -p 5434:5432 postgres:17
sleep 8
docker run --rm --network host -v "$PWD":/w -w /w -e PGPORT=5434 \
  postgres:17 bash scripts/ci_restore_db.sh
```
기대 마지막 출력:
```
products:90
sales_orders:180519
inventory_lots:228
shortage_events:1622
sop_sections:30
완료
```
행 수가 다르면 스크립트가 종료코드 1로 끝난다.

## 3단계: 복원된 DB로 전체 테스트
2단계의 임시 DB(5434)를 가리키게 환경변수를 주고 실행한다.

```bash
B='postgresql://%s:local-dev-only@localhost:5434/pharma'
PHARMA_ADMIN_DSN=$(printf $B pharma_admin) \
PHARMA_RO_DSN=$(printf $B pharma_ro) \
PHARMA_EXT_DSN=$(printf $B pharma_ext) \
uv run pytest -q -rs
```
기대: `36 passed` (skip 없음).

정리:
```bash
docker stop ci-pg-test
```

(선택) `config.py` 기본값(`localhost:5433`) 경로 확인: `docker compose up -d db`로 Compose 서비스 `db`를 띄운 뒤,
빈 DB라면 2단계의 두 번째 명령을 `-e PGPORT=5433`으로 실행하고 환경변수 없이 `uv run pytest -q`를 돌린다.
이미 복원된 볼륨이 있으면 복원 없이 바로 `uv run pytest -q`를 돌린다.

## 4단계: 실제 GitHub Actions에서 확인
`learn/ci-cd` 브랜치를 push하면 `ci` 워크플로가 돈다. Actions 탭에서 `test` job을 열어 확인한다.

| 확인할 것 | 어디서 | 기대 |
|---|---|---|
| 서비스 컨테이너 생성과 헬스체크 | "Initialize containers" 단계 | postgres가 healthy가 된 뒤 첫 스텝 시작 |
| 러너에 `psql` 존재 | `scripts/ci_restore_db.sh` 스텝 | `psql: command not found`가 없을 것 |
| 스크립트 실행 권한 | 같은 스텝 | `Permission denied`가 없을 것 |
| 복원과 행 수 | 같은 스텝 | 위 5줄과 `완료` |
| DB 테스트 실행 | `uv run pytest -q` 스텝 | `36 passed` |

실패 시 단서:
- `Permission denied` → `git ls-files -s scripts/ci_restore_db.sh`가 `100755`인지 확인
- `psql: command not found` → 스텝에서 `postgresql-client` 설치 추가
- 헬스체크 실패 → `options`의 `--health-cmd` 따옴표 확인
- 4개가 그래도 skip → 서비스 컨테이너의 `ports`가 `5433:5432`인지 확인

## 검증 결과 (2026-11-11)
- Actions 실행 `42957186575`(커밋 `768df7a`, `learn/ci-cd`)의 `test` job이 success. 위 4단계 표의 5개 항목을 모두 확인했다.
  서비스 컨테이너 healthy, `psql` 사용 가능, 스크립트 실행 권한 정상, 행 수 5개 일치와 `완료`, `36 passed in 3.62s`.
- `docker` job도 success.
