# pharma-scm-agent

제약 SCM 재고·결품 질의 에이전트. 개인 프로젝트이고 **합성 데이터 위의 질의 에이전트다. 실제 제약사 데이터도, 실제 약품 수요도 아니다.** 실제 서비스 운영 경험이 아니다.

"에이전트가 답했다"에서 멈추지 않고, **정답을 코드가 계산하는 평가셋으로 측정하고, 그 측정을 CI의 배포 관문으로 쓰고, 컨테이너로 AWS에 올려 롤백까지 관찰하는** 흐름을 한 저장소에서 끝까지 해 본 기록이다. 아래에는 확인한 것과 확인하지 못한 것을 함께 적는다.

## 무엇을 하는가
자연어 질문("안전재고 미달 SKU는 몇 개?", "X 성분이 결품이야?", "유통기한 임박 로트는 어떻게 처리해?")에 도구 3개로 답한다. 도구마다 맡는 질문이 겹치지 않는다.

| 도구 | 하는 일 | 안전장치 |
|---|---|---|
| `query_db(sql)` | 재고·발주·판매·리드타임 수치를 SQL로 조회 | 실행 전에 sqlglot으로 SELECT 단일 문·허용 테이블·금지 함수를 검사, 읽기 전용 DB 계정, 행 수·시간 제한 |
| `get_shortage(성분명)` | openFDA 결품 기록 스냅샷 조회 | 별도 읽기 전용 계정 |
| `search_sop(질문)` | 합성 운영 규정(`sop/` 문서 25개, 158개 섹션)을 BM25와 임베딩(bge-m3)을 RRF로 결합해 검색 | DB에 접근하지 않음. 섹션 벡터는 빌드 때 만들고, 문서와 색인의 md5가 다르면 서버가 시작하지 않음 |

단일 에이전트(LangGraph), 모델은 Claude Sonnet 5.5다. 위험·범위 밖 요청(쓰기·시스템 SQL, 복용량 문의 등)은 거절해야 정답으로 채점한다.

## 설계 선택과 이유
- **정답을 코드가 계산한다**: 평가 문항 114개는 템플릿에 정답 SQL(또는 정답 섹션 id)을 함께 두고 정답을 자동 계산한다. 사람이 일일이 대조하지 않아도 재현되고, 채점 기준은 결과를 보기 전에 `docs/eval_protocol.md`에 먼저 적었다(사전 등록).
- **채점기도 검증한다**: 통과한 답의 `최종 답:` 줄을 규칙으로 망가뜨려 541건을 채점기에 넣고 기대대로 판정되는지 봤다.
- **검색 방식도 측정으로 고른다**: 규정 검색 5가지(TF-IDF, BM25, 임베딩, 결합, 재정렬)를 146개 질의로 비교하기 전에 채택 규칙을 먼저 적고(`docs/rag_eval_protocol.md`), 결과대로 결합 방식(R3)을 골랐다. GPU 없는 배포 환경의 지연과 메모리도 따로 쟀다.
- **비용도 같은 방식으로 판정한다**: 프롬프트 캐싱을 "정답 유지 + 입력 비용 20% 이상 감소" 규칙으로 dev/test를 나눠 판정했다(`docs/eval_v2_protocol.md`).
- **CI가 배포 관문이다**: 평가 관련 변경은 스모크 6문항을 돌려 안전·정답률·형식·비용을 `eval/baseline.json` 기준으로 판정하고, 배포 워크플로도 같은 관문을 거친다.
- **인프라는 코드로**: AWS는 Terraform(ECS Fargate, RDS, ALB, IAM)으로 만들고, 배포는 GitHub Actions가 장기 키 없이(OIDC) 맡는다.

## 확인한 것 (근거 문서 포함)
| 영역 | 확인한 내용 | 근거 |
|---|---|---|
| 평가(기준선) | 114문항 1회 111/114(97%), 도구 선택 정확 일치 84/84, 실행 오류 0건 | `docs/eval_results_v1.md` |
| 규정 검색 | 단어가 적게 겹치는 질의 74개에서 상위 3개 정답률 TF-IDF 73.0% → 결합(R3) 95.9%(95% 구간이 겹치지 않음), CPU에서 순위가 GPU와 49/49 같음 | `docs/rag_eval_results.md` §1~§8 |
| 평가(새 검색 연결 후) | v1 114문항 113/114, 평가셋 v2 156문항(새 규정 126, 어려운 DB 30) 156/156 | `docs/rag_eval_results.md` §10, `docs/eval_v2_results.md` |
| 프롬프트 캐싱 | test 78문항 정답 78 → 77(허용 범위), 입력 비용 −75.2%, v1 회귀 확인 통과 | `docs/eval_v2_results.md` §2 |
| 배포 3 (규정 검색 모델 포함) | Fargate 1 vCPU·3GB에서 `/health`·`/ready`·`/ask` 확인, 메모리 약 800MB, 검색 p95 991ms → 질의 임베딩 int8로 236ms, 확인 후 철거 | `docs/rag_eval_results.md` §9, §11~§13 |
| 관측(Langfuse) | 요청·평가 문항마다 트레이스(LLM·도구 단계, 토큰·캐시·비용), 평가 채점을 점수로 기록. 요청 ID와 `<run_id>:<문항>`에서 트레이스 ID를 결정적으로 만들어 로그·결과 파일과 연결. Anthropic SDK의 자체 계측과 겹쳐 비용이 두 배로 합산되던 문제를 찾아 고침 | `docs/langfuse.md` |
| 평가(반복) | 30문항 × 5회 150건 전부 통과, 이 값으로 CI 게이트 임계치를 규칙대로 계산 | `docs/eval_repeat_variance_results.md` |
| 채점기 | 망가뜨린 답 541건이 모두 기대대로 판정 | `docs/eval_results_v1.md` |
| 서버 | FastAPI: `/health`·`/ready` 분리, API 키 인증, 키별 요청 한도, 타임아웃, 요청 ID, JSON 로그와 단계별 시간 | `docs/operations.md` |
| CI | (2026-11-25 기준) `ci.yml`: ruff, pytest 111개(Postgres 복원 포함), Docker 빌드가 push마다 통과. `eval-smoke.yml`: PR에서 스모크 평가와 게이트 판정 통과 | `docs/ci_operations.md` |
| 배포 1 | EC2에 Docker로 임시 배포(CLI, Terraform 각 1회), 외부 호출 검증 후 철거 | `docs/operations.md` |
| 배포 2 | ECS Fargate + RDS + ALB를 Terraform으로 올려 DB 복원, `/health`·`/ready`·`/ask` 확인 후 과금 자원 철거 | `docs/ecs_deploy_walkthrough.md`, `docs/ecs_cost_and_teardown.md` |
| CD | GitHub Actions(OIDC) → 평가 게이트 → ECR push → ECS 롤링 배포를 실제로 실행(리비전 4→5, 응답 확인). 이미지를 받지 못하는 리비전을 일부러 배포해 서킷 브레이커가 약 14분 만에 직전 리비전으로 자동 복귀시키는 것을 관찰 | `HANDOFF.md` 8단계 |

면접에서 설명할 수 있도록 개념별 정리는 `docs/interview_concepts.md`에 있다.

## 한계와 하지 않은 것
- **합성 데이터**: 재고·로트·공급사·발주·SOP는 시드 고정으로 생성했고, DataCo 주문 성과를 약품 SKU에 임의로 매핑한 "수요 패턴의 대역"이다.
- **평가 신뢰도**: 각 결과는 한 번 실행한 값이고, 모델의 `temperature`를 고정할 수 없다. v1(97~99%)과 v2(100%) 모두 정답 조건이 질문에 적힌 문항이라 **상한에 닿아 품질 개선을 구분하지 못한다.** 이 값을 에이전트 일반 성능의 근거로 쓰면 안 된다. 모호한 질문, 문서 모순, 여러 턴 대화처럼 실제로 틀릴 수 있는 문항은 아직 없다.
- **규정 코퍼스**: 규정 문서와 검색 질의는 LLM으로 만든 합성 데이터이고, 문서 사이에 모순이 있다(예: 온도 기록 보관 기간 3/5/7년). 검색 결과에 함께 올라와 답에 드러난다.
- **검색 지연**: Fargate 1 vCPU에서 fp32 검색 p95가 991~1,358ms로 채택 기준(1초 미만)에 여유가 없어, 질의 임베딩을 int8로 양자화해 236ms로 줄였다(정답 포함 여부는 벤치마크 146개 모두 같음, 상위 3개 순서는 48개에서 바뀜). 에이전트 평가는 fp32로 측정했다. 로컬 CPU 제한 측정은 CPU 세대 차이를 반영하지 못했다. 이미지는 모델 때문에 약 4GB다.
- **반복 측정의 낙관성**: 150건 통과에는 기준선에서 실제로 실패한 문항이 포함되지 않았다(결과를 보고 고르지 않으려는 설계).
- **하지 않은 것**: 서술 근거 judge, 멀티 에이전트 비교, 상시 운영(HTTPS, 원격 tfstate, 모니터링). Langfuse는 로컬 실행과 평가에만 연결했고 AWS 배포에는 연결하지 않았다. 규정 검색 구조 변경 뒤의 CI 새 단계(모델 캐시, 색인 빌드)와 자동 배포는 아직 실행하지 않았다.
- **CD의 미확인 범위**: 서킷 브레이커의 정확한 실패 임계값, 앱이 떠서 헬스 체크에 실패하는 경우의 롤백, 수동 롤백, push로 켠 자동 배포의 실제 동작은 확인하지 않았다. 롤백 관찰은 이미지 풀 실패 한 가지 시나리오다.
- **운영 아님**: 사용자도 트래픽도 없다. 태스크 1개 구성이라 가용성 한계가 있다.

## 문서 지도
| 알고 싶은 것 | 문서 |
|---|---|
| 데이터 구성·규칙·한계 | `docs/data_mapping.md` |
| 설계 | `docs/design.md` |
| 평가 규칙(사전 등록)·CI 게이트 | `docs/eval_protocol.md` |
| 평가 결과 | `docs/eval_results_v1.md`, `docs/eval_repeat_variance_results.md` |
| 규정 검색 비교(사전 등록·결과·배포 확인) | `docs/rag_eval_protocol.md`, `docs/rag_eval_results.md` |
| 평가셋 v2와 프롬프트 캐싱(사전 등록·결과) | `docs/eval_v2_protocol.md`, `docs/eval_v2_results.md` |
| 서버 운영과 장애 시 응답 | `docs/operations.md` |
| Langfuse 트레이싱 | `docs/langfuse.md` |
| CI 운영 규칙 | `docs/ci_operations.md` |
| ECS 배포 복습, 비용과 철거 | `docs/ecs_deploy_walkthrough.md`, `docs/ecs_cost_and_teardown.md` |
| 면접 개념 정리 | `docs/interview_concepts.md` |
| 진행 상태와 작업 방식 | `HANDOFF.md` |

## 실행
```bash
docker compose up -d db && uv sync
uv run python -m pharma_scm.build && uv run python -m pharma_scm.evalset.build_evalset
uv run python -m pharma_scm.retrieval.index   # 규정 검색 색인(처음엔 bge-m3 약 2.3GB를 내려받음)
uv run pytest
```

Langfuse(선택): `.env`에 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`을 넣으면 켜진다(`docs/langfuse.md`).

서버: `.env`에 `PHARMA_API_KEY`를 넣고 `uv run uvicorn pharma_scm.api.main:app --port 8000`. 엔드포인트와 장애 시 응답은 `docs/operations.md`. 평가 실행은 LLM을 호출하므로 비용이 든다(스모크 6문항은 호출 약 10회, 전체 114문항은 약 225회). 평가셋 v2는 `run_eval --set v2 [--split dev|test]`, 비교는 `report_v2 <기준> <개선>`.

## 출처
DataCo Smart Supply Chain (CC BY 4.0, 가공함), openFDA 결품 데이터. 자세한 표기는 `docs/data_mapping.md`. 가공한 DB 스냅샷(`deploy/pharma.sql.gz`)에도 같은 출처 표기가 적용된다.
