# pharma-scm-agent

제약 SCM 재고·결품 질의 에이전트(개인 프로젝트). **합성 데이터 기반으로, 실제 제약사 데이터도 실제 약품 수요도 아님.** 실서비스 운영 이력 없음.

**정답을 코드로 계산한 평가셋으로 에이전트를 측정하고, 그 측정을 CI 배포 관문으로 쓰고, 컨테이너로 AWS에 배포해 롤백까지 관찰한** 기록. 확인한 것과 확인하지 못한 것을 함께 정리.

## 기능
자연어 질문("안전재고 미달 SKU는 몇 개?", "X 성분이 결품이야?", "유통기한 임박 로트는 어떻게 처리해?")에 도구 3개로 답함. 도구별 담당 질문은 겹치지 않음.

| 도구 | 하는 일 | 안전장치 |
|---|---|---|
| `query_db(sql)` | 재고·발주·판매·리드타임 수치를 SQL로 조회 | 실행 전에 sqlglot으로 SELECT 단일 문·허용 테이블·금지 함수를 검사, 읽기 전용 DB 계정, 행 수·시간 제한 |
| `get_shortage(성분명)` | openFDA 결품 기록 스냅샷 조회 | 별도 읽기 전용 계정 |
| `search_sop(질문)` | 합성 운영 규정(`sop/` 문서 25개, 158개 섹션)을 BM25와 임베딩(bge-m3)을 RRF로 결합해 검색 | DB에 접근하지 않음. 섹션 벡터는 빌드 때 만들고, 문서와 색인의 md5가 다르면 서버가 시작하지 않음 |

단일 에이전트(LangGraph), 모델은 Claude Sonnet 5.5. 위험·범위 밖 요청(쓰기·시스템 SQL, 복용량 문의 등)은 거절해야 정답으로 채점.

## 설계 선택과 이유
- **정답은 코드가 계산**: 평가 문항 114개는 템플릿에 정답 SQL(또는 정답 섹션 id)을 함께 두고 정답을 자동 계산. 사람이 대조하지 않아도 재현되며, 채점 기준은 결과를 보기 전에 먼저 기록(사전 등록).
- **채점기도 검증**: 통과한 답의 `최종 답:` 줄을 규칙으로 망가뜨린 541건을 채점기에 넣어 기대대로 판정되는지 확인.
- **검색 방식도 측정으로 선택**: 규정 검색 5가지(TF-IDF, BM25, 임베딩, 결합, 재정렬)를 146개 질의로 비교하기 전에 채택 규칙을 먼저 정하고 결과에 따라 결합 방식(R3) 채택. GPU 없는 배포 환경의 지연과 메모리도 별도 측정.
- **비용도 같은 방식으로 판정**: 프롬프트 캐싱을 "정답 유지 + 입력 비용 20% 이상 감소" 규칙으로 dev/test를 나눠 판정.
- **CI가 배포 관문**: 평가 관련 변경은 스모크 6문항을 돌려 안전·정답률·형식·비용을 `eval/baseline.json` 기준으로 판정. 배포 워크플로도 같은 관문을 거침.
- **인프라는 코드로**: AWS는 Terraform(ECS Fargate, RDS, ALB, IAM)으로 구성, 배포는 GitHub Actions가 장기 키 없이(OIDC) 수행.

## 확인한 것
| 영역 | 확인한 내용 | 코드 |
|---|---|---|
| 평가(기준선) | 114문항 1회 111/114(97%), 도구 선택 정확 일치 84/84, 실행 오류 0건 | `src/pharma_scm/evalset/`, `eval/questions.jsonl` |
| 규정 검색 | 단어가 적게 겹치는 질의 74개에서 상위 3개 정답률 TF-IDF 73.0% → 결합(R3) 95.9%(95% 구간이 겹치지 않음), CPU에서 순위가 GPU와 49/49 같음 | `src/pharma_scm/retrieval/` |
| 평가(새 검색 연결 후) | v1 114문항 113/114, 평가셋 v2 156문항(새 규정 126, 어려운 DB 30) 156/156 | `eval/questions_v2.jsonl` |
| 프롬프트 캐싱 | test 78문항 정답 78 → 77(허용 범위), 입력 비용 −75.2%, v1 회귀 확인 통과 | `src/pharma_scm/agent/graph.py` |
| 배포 3 (규정 검색 모델 포함) | Fargate 1 vCPU·3GB에서 `/health`·`/ready`·`/ask` 확인, 메모리 약 800MB, 검색 p95 991ms → 질의 임베딩 int8로 236ms, 확인 후 철거 | `Dockerfile`, `deploy/terraform-ecs/` |
| 멀티 에이전트 비교 | 감독+전문가 3(M)과 단일(S)을 같은 모델·도구·프롬프트 문구로 평가셋 v3 30문항에서 비교: 정답 30/30 대 30/30, M 비용 +108%, 지연 2.2배 → 사전 등록 규칙대로 S 유지. 원인은 전문가 보고가 출력 상한에 걸려 비고 감독이 재위임한 것(트레이스로 확인) | `src/pharma_scm/agent/multi.py`, `eval/questions_v3.jsonl` |
| 관측(Langfuse) | 요청·평가 문항마다 트레이스(LLM·도구 단계, 토큰·캐시·비용), 평가 채점을 점수로 기록. 요청 ID와 `<run_id>:<문항>`에서 트레이스 ID를 결정적으로 만들어 로그·결과 파일과 연결. Anthropic SDK의 자체 계측과 겹쳐 비용이 두 배로 합산되던 문제를 찾아 고침 | `src/pharma_scm/agent/tracing.py` |
| 평가(반복) | 30문항 × 5회 150건 전부 통과, 이 값으로 CI 게이트 임계치를 규칙대로 계산 | `src/pharma_scm/evalset/gate.py`, `eval/baseline.json` |
| 채점기 | 망가뜨린 답 541건이 모두 기대대로 판정 | `src/pharma_scm/evalset/grader.py`, `make_broken_runs.py` |
| 서버 | FastAPI: `/health`·`/ready` 분리, API 키 인증, 키별 요청 한도, 타임아웃, 요청 ID, JSON 로그와 단계별 시간 | `src/pharma_scm/api/` |
| CI | `ci.yml`: ruff, pytest(Postgres 복원 포함, 2026-11-27 149 passed·2 skipped), 규정 검색 모델 캐시와 색인 빌드, Docker 빌드가 push마다 통과. `eval-smoke.yml`: PR에서 스모크 평가와 게이트 판정 통과 | `.github/workflows/ci.yml`, `eval-smoke.yml` |
| 배포 1 | EC2에 Docker로 임시 배포(CLI, Terraform 각 1회), 외부 호출 검증 후 철거 | `deploy/terraform/`, `deploy/compose.deploy.yaml` |
| 배포 2 | ECS Fargate + RDS + ALB를 Terraform으로 올려 DB 복원, `/health`·`/ready`·`/ask` 확인 후 과금 자원 철거 | `deploy/terraform-ecs/` |
| CD | GitHub Actions(OIDC) → 평가 게이트 → ECR push → ECS 롤링 배포를 실제로 실행(리비전 4→5, 응답 확인). 이미지를 받지 못하는 리비전을 일부러 배포해 서킷 브레이커가 약 14분 만에 직전 리비전으로 자동 복귀시키는 것을 관찰. 이 공개 저장소에서도 수동 실행 배포 성공(2026-11-27, 리비전 9→10, Actions 실행 기록 공개) | `.github/workflows/deploy.yml` |

## 한계와 하지 않은 것
- **합성 데이터**: 재고·로트·공급사·발주·SOP는 시드 고정으로 생성. 수요는 DataCo 주문 성과를 약품 SKU에 임의로 매핑한 "수요 패턴의 대역".
- **평가 신뢰도**: 각 결과는 1회 실행 값이며, 모델의 `temperature`는 고정할 수 없음. v1(97~99%)과 v2(100%) 모두 정답 조건이 질문에 적힌 문항이라 **상한에 닿아 품질 개선을 구분하지 못함.** 이 값은 에이전트 일반 성능의 근거가 될 수 없음. 모호한 질문, 문서 모순, 여러 턴 대화처럼 실제로 틀릴 수 있는 문항은 아직 없음.
- **규정 코퍼스**: 규정 문서와 검색 질의는 LLM으로 만든 합성 데이터이며, 문서 간 모순이 있음(예: 온도 기록 보관 기간 3/5/7년). 검색 결과에 함께 올라와 답에 드러남.
- **검색 지연**: Fargate 1 vCPU에서 fp32 검색 p95가 991~1,358ms로 채택 기준(1초 미만)에 여유가 없어 질의 임베딩을 int8로 양자화해 236ms로 단축(정답 포함 여부는 벤치마크 146개 모두 같음, 상위 3개 순서는 48개에서 바뀜). 에이전트 평가는 fp32로 측정. 로컬 CPU 제한 측정은 CPU 세대 차이를 반영하지 못함. 이미지는 모델 때문에 약 4GB.
- **반복 측정의 낙관성**: 150건 통과에 기준선에서 실제로 실패한 문항은 포함되지 않음(결과를 보고 문항을 고르지 않기 위한 설계).
- **하지 않은 것**: 서술 근거 judge, judge가 필요한 문항(모호한 질문, 여러 턴 대화), 상시 운영(HTTPS, 원격 tfstate, 모니터링). Langfuse는 로컬 실행과 평가에만 연결했고 AWS 배포에는 연결하지 않음. master push로 시작하는 자동 배포(저장소 변수 `DEPLOY_ENABLED`로 켬)는 실행하지 않았고, 배포는 수동 실행으로만 진행.
- **CD의 미확인 범위**: 서킷 브레이커의 정확한 실패 임계값, 앱이 떠서 헬스 체크에 실패하는 경우의 롤백, 수동 롤백, push로 켠 자동 배포의 실제 동작은 확인하지 않음. 롤백 관찰은 이미지 풀 실패 한 가지 시나리오.
- **운영 아님**: 사용자도 트래픽도 없음. 태스크 1개 구성이라 가용성에 한계가 있음.

## 실행
```bash
docker compose up -d db && uv sync
uv run python -m pharma_scm.build && uv run python -m pharma_scm.evalset.build_evalset
uv run python -m pharma_scm.retrieval.index   # 규정 검색 색인(최초 실행 시 bge-m3 약 2.3GB 다운로드)
uv run pytest
```

Langfuse(선택): `.env`에 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`을 넣으면 활성화.

서버: `.env`에 `PHARMA_API_KEY`를 넣고 `uv run uvicorn pharma_scm.api.main:app --port 8000`. 평가 실행은 LLM을 호출하므로 비용 발생(스모크 6문항은 호출 약 10회, 전체 114문항은 약 225회). 평가셋 v2는 `run_eval --set v2 [--split dev|test]`, 비교는 `report_v2 <기준> <개선>`.

## 출처
- DataCo Smart Supply Chain: Constante, Fabian; Silva, Fernando; Pereira, António (2019), *DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS*, Mendeley Data, 버전 5, CC BY 4.0. 제품을 약품 SKU에 매핑하는 등 가공함.
- openFDA 결품 데이터(`/drug/shortages.json`, 2026-11-02 스냅샷). openFDA 안내: "Do not rely on openFDA to make decisions regarding medical care." 의료 판단에 쓰지 않음.
- 공급사·SKU 구성·재고 로트·발주·SOP는 합성.

가공한 DB 스냅샷(`deploy/pharma.sql.gz`)에도 같은 출처 표기 적용.
