# Langfuse 트레이싱 (2026-11-26)

에이전트 실행을 Langfuse Cloud에 트레이스로 남기고, 평가 채점 결과를 트레이스 점수로 붙인다. **선택 기능이다.** `.env`에 키가 없거나 `LANGFUSE_TRACING_ENABLED=false`면 아무것도 하지 않는다. CI, 시험(`tests/conftest.py`에서 끔), AWS 배포에는 키를 두지 않아 영향이 없다.

## 1. 설정
`.env`(값은 커밋하지 않는다):
```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com     # 리전 API 주소. 프로젝트 화면 주소(/project/...)가 아니다
```
SDK는 `langfuse==5.2.0`. 공식 문서 사이트를 이 PC에서 열지 못해 API는 **설치된 패키지 소스**로 확인했다(`langfuse/langchain/CallbackHandler.py`, `langfuse/_client/client.py`).

## 2. 무엇이 기록되나 (`src/pharma_scm/agent/tracing.py`)
| 실행 경로 | 트레이스 이름 | 트레이스 ID를 만드는 외부 ID | 세션 | 태그 | 메타데이터 |
|---|---|---|---|---|---|
| API `/ask` | `api_ask` | 요청 ID(`X-Request-ID` 또는 서버가 만든 값) | 없음 | `api` | `request_id` |
| 평가 `run_eval` | `eval` | `<run_id>:<문항 ID>` | run_id | `eval`, 평가셋, 유형 | `eval_run_id`, `question_id`, `question_type`, `split` |
| CLI `agent.run` | `cli` | 없음(무작위) | 없음 | 없음 | 없음 |

- 공통 메타데이터: `prompt_version`, `prompt_sha`, `prompt_cache`, `model`.
- 트레이스 ID는 외부 ID에서 결정적으로 만든다(`Langfuse.create_trace_id(seed=...)`). API 응답과 서버 로그의 `trace_id`, 평가 결과 파일(`data/runs/<run_id>/<문항>.json`)의 `trace_id`로 Langfuse에서 바로 찾는다. 클라이언트가 같은 요청 ID를 재사용하면 같은 트레이스에 합쳐진다.
- 트레이스 안: LangGraph 노드(agent, tools), LLM 호출(GENERATION, 토큰·캐시 토큰·비용), 도구 호출(TOOL, 입력·결과).
- 평가 점수: `pass`, `format_ok`(항상), `tool_exact`(정답 도구가 하나인 문항만). 모두 BOOLEAN. 실패 이유를 `pass`의 comment로 보낸다.

## 3. 확인한 것 (직접 확인, Anthropic 비용 약 $0.1)
- 평가 10문항(v1 A·B·C·D·E 7개, v2 G·H 3개)과 로컬 API `/ask` 1회를 실행해 Langfuse v2 관측 조회 API로 읽었다.
- 문항마다 트레이스 1개, 도구 단계(입력·결과 있음), 점수 2~3개가 기대대로 들어갔다. 실패 문항(E009)은 `pass=False`, `format_ok=False`.
- API 경로: 응답의 `trace_id`가 요청 ID에서 계산한 값과 같고, 루트 관측의 메타데이터에 `request_id`가 들어 있다.
- 캐시 토큰: 동시에 시작한 첫 호출들에서 캐시 쓰기 2,207토큰이 우리 집계(`tokens.cache_write`)와 Langfuse 양쪽에 잡혔다. `docs/eval_v2_results.md` §2에 "확인하지 못했다"고 적었던 쓰기 집계가 맞게 동작함을 이번에 확인했다.

## 4. 발견한 문제와 처리
1. **같은 LLM 호출이 두 번 기록됨 → 고침.** Anthropic SDK(2.4.0)는 전역 OpenTelemetry 트레이서가 있으면 API 호출마다 자체 span(`anthropic.messages.create`)을 만든다. Langfuse 5.x가 OpenTelemetry 기반이라 이 span도 함께 보내져, LangChain 콜백의 GENERATION 아래에 같은 호출이 하나 더 생기고 트레이스 비용이 두 배로 합산됐다. `ANTHROPIC_OPEN_TELEMETRY=false`를 클라이언트 생성 전에 설정해 끈다(`agent/graph.py make_llm`). 고친 뒤 LLM 호출 1번에 GENERATION 1개.
2. **캐시 쓰기 토큰의 합계 표시가 두 배 → 그대로 둠.** LangChain 콜백 기록은 캐시 쓰기 토큰을 합계 키와 TTL별 키에 모두 넣어 `total`이 두 배로 보인다(예: 2,424 → 4,631). 비용은 두 키를 중복 계산하지 않아 맞다(0.0068475달러, 손 계산과 일치).
3. **캐시 읽기 단가 차이 → 기록만 함.** Langfuse는 이 모델의 캐시 읽기를 100만 토큰당 $0.10으로 계산했다. 이 저장소의 비용 계산(`report_v2.PRICE`)은 Anthropic 공시 $0.20(알고 있는 기준)을 쓴다. 입력 $2, 출력 $10은 같다. 맞추려면 Langfuse 프로젝트 설정에서 모델 단가를 직접 지정한다(하지 않음).
4. **옛 트레이스 조회 API 폐기.** `GET /api/public/traces/{id}`는 Langfuse Cloud에서 2026-11-16에 제거되어 410을 돌려준다. 확인에는 `api.observations.get_many(trace_id=..., from_start_time=...)`(v2)와 `api.scores.get_many(trace_id=...)`를 썼다. 앱 코드는 조회 API를 쓰지 않는다.
5. **이 PC의 HTTPS 검사.** 처음 연결 몇 번은 회사 네트워크 장비가 `cloud.langfuse.com`의 HTTPS를 가로채 자체 인증서로 바꿔 Python이 거부했다(`self-signed certificate in certificate chain`). 몇 분 뒤에는 원래 인증서(Amazon)로 연결됐고 이유는 확인하지 못했다. 인증서 설정은 바꾸지 않았다. 다시 생기면 회사 루트 인증서를 이 프로젝트에서만 신뢰하는 방법(`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`)을 쓴다.

## 5. 한계
- 트레이싱이 응답 지연에 주는 영향은 따로 재지 않았다(전송은 백그라운드 배치).
- 질문, 답, 도구 결과(DB 행, 규정 본문)가 외부 서비스로 나간다. 합성 데이터라 허용했다. 실제 데이터라면 마스킹이나 셀프 호스팅이 필요하다.
- AWS 배포에는 연결하지 않았다(키를 SSM에 두면 켜진다, 하지 않음).
