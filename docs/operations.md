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
