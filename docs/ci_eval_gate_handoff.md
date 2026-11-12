# CI 평가 게이트: 새 세션 인계 (2026-11-11 작성, 브랜치 `learn/ci-cd`)

설계와 과제 1~6 전체는 `docs/ci_eval_gate_plan.md`에 있다. 이 문서는 **그 뒤의 진행 상태와, 세션에서 합의한 작업 방식**만 적는다. 두 문서를 같이 읽는다.

## 진행 상태
| 과제 | 상태 | 근거 |
|---|---|---|
| 1. CI에 Postgres 서비스 + 덤프 복원 | **완료** | 커밋 `768df7a` push됨. Actions 실행 `42957186575`에서 `36 passed`, skip 0 확인 |
| 2. `gold_sql` ↔ `gold` 일치 테스트 | 미착수 (이번 묶음) | |
| 3. 문항 md5·프롬프트 해시 등록값 비교 | 미착수 (이번 묶음) | |
| 4~6 | 미착수 | 4·6은 LLM 호출이라 비용 계산 후 승인 필요 |

진행 묶음: 사용자가 **2·3을 한 묶음**으로 진행하기로 했다. 순서는 2 → 3.

과제 1 산출물: `.github/workflows/ci.yml`(test job의 `services: postgres`, `ci_restore_db.sh` 스텝), `scripts/ci_restore_db.sh`, `docs/ci_task1_verify.md`(개인 PC 검증 절차와 결과).
`docs/ci_task1_verify.md`의 "검증 결과" 갱신은 이 인계 시점에 **커밋되지 않은 변경**일 수 있다. `git status`로 확인한다.

## 작업 방식 (사용자와 합의, 반드시 지킬 것)
- **파일 하나씩 단계를 밟는다.** 한 번에 여러 파일을 만들어 놓고 설명하지 않는다. 파일마다 "무엇을, 왜, 어떻게"를 설명하고 확인받은 뒤 다음 파일로 간다. (사용자가 과제 1에서 이 점을 지적했다.)
- **용어를 구분해서 정확히 쓴다.** 뭉뚱그리지 않는다.
  - 이미지(설계도) / 컨테이너(실행 중인 환경) / 호스트(컨테이너를 돌리는 머신: 로컬은 이 PC, CI는 GitHub 러너)
  - "서비스"는 두 가지다: **Compose 서비스**(`compose.yaml`의 `db`)와 **Actions 서비스 컨테이너**(`ci.yml`의 `services:`). 서로 다른 도구다.
  - 로컬 DB는 Compose 서비스 `db`의 컨테이너(`pharma-scm-agent-db-1`), CI의 DB는 job마다 새로 생기고 사라지는 별개의 컨테이너다.
- 설명은 파일 위→아래가 아니라 **실행되는 시간 순서(평가 절차: 재료 고정→실행→채점→집계→판정→보관→연결)** 로 한다. 사용자는 Unity/C# 개발자이고 서버·CI가 처음이다. Unity 비유는 도움이 됐다.
- 질문이 나오면 "개념이 없어서"로 단정하지 않는다. 사용자는 보통 설명에서 빠진 연결을 정확히 짚는다.
- 커밋·push는 **사용자가 요청할 때만**. 작업 단위가 끝나면 "커밋할까요"를 묻는다. 파일을 **지정해서** add한다(`git add -A` 금지).
- `data/raw/openfda_shortages_2026-11-02_0.json`, `..._1000.json`, `openfda_result.txt`의 변경은 의도적으로 커밋하지 않는 것이다. 건드리지 않는다.
- 검증하지 않은 것은 "미검증"이라고 적는다. 검증했으면 어떻게 했는지 말한다.
- LLM을 실제로 호출하는 작업(과제 4, 6)은 호출 수·토큰·비용을 먼저 계산해 보여주고 승인받는다.
- 대명사를 모르면 they/them. 타입 힌트 없음(저장소 스타일), 주석은 한국어, 기존 밀도에 맞춘다.

## 이 환경에서 확인된 사실
- **`gh` CLI가 설치되어 있고 로그인되어 있다**(계정 SeonHwan). Actions 결과를 직접 볼 수 있다: `gh run list --branch learn/ci-cd`, `gh run view <id> --log`. `git push`도 이 PC에서 인증서 오류 없이 된다. 저장소는 `https://github.com/SeonHwan/pharma-scm-agent`.
- 이 PC에는 호스트용 `psql`이 **없다**. psql이 필요한 스크립트는 `docker run --rm --network host -v "$PWD":/w -w /w postgres:17 bash ...`로 돌린다.
- 로컬 DB는 어제까지 꺼져 있다가 다시 올렸다. 새 세션에서 `docker ps`로 `pharma-scm-agent-db-1`이 떠 있는지 확인하고, 없으면 `docker compose up -d db`. 없는 채로 `uv run pytest`를 돌리면 `32 passed, 4 skipped`가 나온다(DB 테스트 skip).
- 일부 MCP 서버는 `SELF_SIGNED_CERT_IN_CHAIN`으로 연결에 실패한다. 사내 TLS 가로채기 환경으로 보이며, **Anthropic API 호출이 이 PC에서 되는지는 아직 확인하지 않았다.** 과제 4 전에 최소 호출로 확인한다. 안 되면 개인 PC에서 한다(개인 PC로 옮길 때는 git 밖의 `data/runs/main_v1/`와 API 키가 필요하다. 과제 5의 `baseline.json` 재집계에 `main_v1`이 쓰인다).
- 현재 CI 테스트는 36개이고 모두 통과한다. 새 테스트를 넣으면 36보다 늘어난다.
- `uv run pytest -q`, `uv run ruff check .`가 로컬 검증 명령이다.

## 다음 작업: 과제 2 (이어서 3)

### 과제 2: `tests/test_evalset_gold.py`
- A 유형 문항의 `gold_sql`을 **읽기 전용 계정(`config.RO_DSN`)** 으로 실행해 결과가 `gold.value`와 같은지 확인. 정수는 정확히, 소수는 채점기와 같은 ±0.05 규칙이므로 `src/pharma_scm/evalset/grader.py`의 `_num_ok(got, gold)`를 재사용한다(`isinstance(gold, int)`면 `==`, 아니면 `abs(got-gold) <= DECIMAL_TOL`).
- `needs_db` 픽스처(`tests/conftest.py`) 사용. 문항은 `eval/questions.jsonl`에서 읽는다(한 줄 = JSON 하나: `id, type, question, expected_tools, gold{kind,value}, gold_sql`).
- **먼저 확인할 것:** 계획서는 "`gold_sql`은 A 44개에만 있다"고 적었는데 `docs/eval_protocol.md`는 "A·D의 `gold_sql`"이라고 적었다. 실제로 `gold_sql` 필드가 있는 문항을 세어 어느 쪽이 맞는지 확인하고, 있는 문항 전체를 대상으로 한다. 값이 불일치하는 문항이 나오면 **테스트를 고치지 말고 사용자에게 보고**한다(정답표 오류일 수 있다).
- 예시 SQL(A001): `SELECT coalesce(sum(quantity),0) FROM inventory_lots WHERE warehouse='WH-INC' AND lot_status='available' AND expiry_date >= DATE '2026-11-01'`, 기대값 189779.
- 결과가 `Decimal`로 올 수 있으니 비교 전 숫자 타입을 확인한다.
- 완료 기준: 로컬(DB 켠 상태)과 CI 모두에서 통과, DB 없으면 skip.

### 과제 3: 등록값 비교
- `eval/registered.json` = `{"questions_md5": "e96780f475db1108c1e3a4eb35a2fe67", "prompt_version": "v1", "prompt_sha": "b92313567d93"}`.
- `tests/test_eval_registration.py`: 현재 `eval/questions.jsonl`의 md5, `agent/prompt.py`의 `PROMPT_VERSION`, `PROMPT_SHA`를 등록값과 비교. 다르면 실패하고 메시지에 "의도한 변경이면 버전을 올리고 registered.json과 baseline을 PR로 갱신"을 안내한다.
- **등록 전에 현재 값을 직접 계산해서 확인한다.** 이 세션에서 `md5sum eval/questions.jsonl` = `e96780f475db1108c1e3a4eb35a2fe67`(일치)을 확인했다. `PROMPT_SHA`(`b92313567d93`)는 아직 확인하지 않았다. `PROMPT_SHA`는 `agent/prompt.py` 끝에서 `SYSTEM_PROMPT`의 sha256 앞 12자리로 계산된다.
- 이 테스트는 DB가 필요 없다. 파일 읽기만 한다.

## 이후 순서 (계획서 기준)
2 → 3 → 5의 코드 부분(`--ids`, `report --json`, `gate.py` + 단위 테스트) → 4(승인 후 측정) → 임계치 확정·`baseline.json` → 6.
완료 후 갱신: `docs/eval_protocol.md`, `HANDOFF.md`(한 줄), `~/server-tutorial/step05_ci_eval_gate.md`(갱신 여부는 사용자에게 묻는다).
