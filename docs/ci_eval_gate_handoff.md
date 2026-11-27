# CI 평가 게이트: 인계 (2026-11-12 갱신, `master`)

설계 배경과 과제 1~6 전체는 `docs/ci_eval_gate_plan.md`에 있다(설계 기록으로만 읽는다). 운영은 `docs/ci_operations.md`, 게이트 규칙·임계치는 `docs/eval_protocol.md`의 "CI 게이트" 절. 이 문서는 **진행 상태와, 세션에서 합의한 작업 방식**만 적는다.

## 진행 상태: 과제 1~6 모두 완료
| 과제 | 결과 | 근거 |
|---|---|---|
| 1. CI에 Postgres 서비스 + 덤프 복원 | 완료 | `scripts/ci_restore_db.sh`, `ci.yml`. Actions에서 skip 0 확인 |
| 2. `gold_sql` ↔ `gold` 일치 테스트 | 완료 | `tests/test_evalset_gold.py`(A 44개) |
| 3. 문항 md5·프롬프트 해시 등록값 비교 | 완료 | `eval/registered.json`, `tests/test_eval_registration.py` |
| 4. repeat-variance 측정 | 완료 | 30문항×5회 150건 전부 통과. `docs/eval_repeat_variance.md`(사전 등록), `..._results.md`(결과) |
| 5. `run_eval` 확장, `report --json`, `gate.py`, `baseline.json` | 완료 | `evalset/gate.py`, `eval/baseline.json`, `tests/test_gate.py` |
| 6. 스모크·전체 평가 워크플로 | 완료 | `eval-smoke.yml`(PR #1에서 6문항 PASS·게이트 통과), `eval-full.yml`(실행 `43171436991`: 114문항 112/114) |

PR #1(머지 `fd930ea`)과 PR #2(문서, `43c2416`)가 `master`에 들어갔다. 현재 `master`의 pytest는 **111개**이고 skip 0이다(DB가 켜져 있을 때).
**미검증으로 남은 것**: 게이트가 Actions에서 job을 실제로 실패시키는 경로(단위 테스트만), fork PR 스킵, 웹의 "Run workflow" 버튼 화면. 한계: 무료 플랜 비공개 저장소라 branch protection을 쓸 수 없다(`docs/ci_operations.md`).

## 이어서 할 일
이 문서의 범위(평가 게이트)는 끝났다.

## 작업 방식 (사용자와 합의, 반드시 지킬 것)
- **`master`에서 바로 작업한다.** CI 학습용 브랜치 `learn/ci-cd`는 머지로 끝났다(사용자 합의 2026-11-12: 혼자 쓰는 저장소이고 branch protection도 못 쓰니 문서·코드 변경에 PR을 요구하지 않는다). PR은 `eval-smoke`처럼 PR 이벤트를 검증해야 할 때만 쓴다.
- **파일 하나씩 단계를 밟는다.** 한 번에 여러 파일을 만들어 놓고 설명하지 않는다. 파일마다 "무엇을, 왜, 어떻게"를 설명하고 확인받은 뒤 다음으로 간다.
- **용어를 구분해서 정확히 쓴다.** 이미지(설계도) / 컨테이너(실행 중인 환경) / 호스트(컨테이너를 돌리는 머신: 로컬은 이 PC, CI는 GitHub 러너). "서비스"는 두 가지다: Compose 서비스(`compose.yaml`의 `db`)와 Actions 서비스 컨테이너(`ci.yml`의 `services:`). 로컬 DB와 CI의 DB는 별개의 컨테이너다.
- 설명은 파일 위→아래가 아니라 **실행되는 시간 순서**로 한다. 사용자는 서버·CI·AWS가 처음인 개발자다. **비유를 쓰지 않는다**(2026-11-19 사용자 요청). 개념 자체와 이 프로젝트의 실물로 설명한다. 질문이 나오면 "개념이 없어서"로 단정하지 않는다. 사용자는 보통 설명에서 빠진 연결을 정확히 짚는다.
- 커밋·push는 **사용자가 요청할 때만**. 작업 단위가 끝나면 "커밋할까요"를 묻는다. 파일을 **지정해서** add한다(`git add -A` 금지).
- `data/raw/openfda_shortages_2026-11-02_0.json`, `..._1000.json`, `openfda_result.txt`의 변경은 의도적으로 커밋하지 않는 것이다. 건드리지 않는다.
- 검증하지 않은 것은 "미검증"이라고 적는다. 검증했으면 어떻게 했는지 말한다. 사용자가 보는 화면(AWS 콘솔 등)은 직접 볼 수 없으니 메뉴 이름은 "알고 있는 기준"이라고 밝힌다.
- **LLM·AWS 비용이 드는 작업은 호출 수·토큰·비용을 먼저 계산해 보여 주고 승인받는다.** 비용 자원은 끝나면 철거하고 철거 확인 방법을 적는다.
- 대명사를 모르면 they/them. 타입 힌트 없음(저장소 스타일), 주석은 한국어, 기존 밀도에 맞춘다.

## 이 환경에서 확인된 사실
- **`gh`가 설치·로그인(SeonHwan)되어 있다.** `gh run list --branch master`, `gh run view <id> --log`, `gh run download <id> -n <artifact> -D <새 폴더>`, `gh workflow run eval-full.yml --ref master -f approve_cost=true`가 동작한다. `git push`도 된다. 이 PC에서 **Anthropic API 호출도 된다**(2026-11-12 확인).
- 이 PC에는 호스트용 `psql`이 **없다**. 필요하면 `docker run --rm --network host -v "$PWD":/w -w /w postgres:17 bash ...`.
- **로컬 DB 컨테이너(`pharma-scm-agent-db-1`)가 자주 꺼져 있다**(세션 중 두 번 확인됨, 원인 미확인). 꺼져 있으면 DB 테스트가 실패가 아니라 skip되어 `passed`만 보면 놓친다. `docker ps`로 확인하고 `docker compose up -d db`. 로컬 검증은 `uv run pytest -q`와 `uv run ruff check .`.
- 일부 MCP 서버는 `SELF_SIGNED_CERT_IN_CHAIN`으로 연결에 실패한다(사내 TLS 가로채기로 보임). AWS 호출도 이 PC에서는 안 되는 것으로 기록되어 있다.
- 2026-11-12에 작업 트리의 `deploy/*.sh`, `scripts/ci_restore_db.sh` 6개가 CRLF로 바뀌고 실행 권한이 빠진 적이 있다(Claude가 한 일이 아님, `git restore`로 복구함). 다시 보이면 `git diff --summary`와 `grep -c $'\r'`로 확인한다.
- 비용 규모(실측): 스모크 6문항은 호출 약 10회·입력 약 2.5만 토큰, 전체 114문항은 호출 225회·입력 약 58.7만 토큰.
