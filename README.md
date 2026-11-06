# pharma-scm-agent

제약 SCM 재고·결품 질의 에이전트(진행 중). **합성 데이터 위의 질의 에이전트다. 실제 제약사 데이터·실제 약품 수요가 아니다.**

- 데이터 구성·규칙·한계: `docs/data_mapping.md`
- 설계: `docs/design.md`, 평가 사전 등록: `docs/eval_protocol.md`
- 출처: DataCo Smart Supply Chain (CC BY 4.0, 가공함), openFDA 결품 데이터. 자세한 표기는 `docs/data_mapping.md`.

```bash
docker compose up -d db && uv sync
uv run python -m pharma_scm.build && uv run python -m pharma_scm.evalset.build_evalset
uv run pytest
```

## 서버
`.env`에 `PHARMA_API_KEY`를 넣고 `uv run uvicorn pharma_scm.api.main:app --port 8000`. 엔드포인트와 장애 시 응답은 `docs/operations.md`.
