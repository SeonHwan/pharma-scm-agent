# 데이터 구성과 매핑 규칙

**합성 데이터 위의 질의 에이전트용 데이터다. 실제 제약사 내부 데이터가 아니고, 실제 약품 수요도 아니다.**
이 문서는 코드(`src/pharma_scm/`)가 실제로 하는 일을 적은 것이다. 코드와 다르면 코드가 맞다.

## 출처
| 데이터 | 출처 | 비고 |
|---|---|---|
| 주문·배송 | DataCo Smart Supply Chain (Mendeley Data, 버전 5, CC BY 4.0) | 출처: Constante, Fabian; Silva, Fernando; Pereira, António (2019), *DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS*, Mendeley Data. 가공했음(아래 규칙) |
| 결품 | openFDA `GET https://api.fda.gov/drug/shortages.json` | 1,622건, `meta.last_updated` = 2026-11-02. `/drug/drugshortages.json`은 응답 없음(확인함) |
| 공급사·SKU 구성·재고 로트·발주·SOP | **합성** | `random.Random(f"{SEED}:{이름}")`, 기준일 2026-11-01 고정 |

openFDA 안내문: "Do not rely on openFDA to make decisions regarding medical care." 이 프로젝트는 의료 판단에 쓰지 않는다.

## 매핑 규칙 (고정)
- **SKU 90개** = openFDA 성분명 80개(층화 추출: Resolved 포함 5, Current+단종예정 혼재 6, Current만 40, 단종예정만 29) + 결품 기록이 없는 성분 10개(음성 사례, 스냅샷 성분명의 첫 단어와 겹치지 않는 것만). SKU 번호는 섞어서 부여한다(번호로 결품 여부를 알 수 없다).
- **DataCo 제품 118개 → SKU 90개**: `Product Card Id`를 오름차순으로 세워 SKU에 순환 배정한다. 일부 SKU는 DataCo 제품 둘을 합친다. 제품의 실제 성격(스포츠용품 등)은 버린다 — **수요·배송 패턴의 대역일 뿐이다.**
- **날짜**: 마지막 주문일(2018-01-31)이 기준일 하루 전(2026-10-31)이 되도록 +3,195일 이동(2015-01 → 2023-10).
- **수량**: DataCo `Order Item Quantity`(1~5) × 100 = 박스 수.
- 적재 컬럼: 주문·품목 id, 주문일, 수량, 실제/계획 배송일수, 지연 여부, 배송 상태, 주문 상태, 시장. 고객 정보(이름·이메일·주소 등)는 적재하지 않는다.
- openFDA의 `strength` 필드는 없다(함량은 `presentation` 문자열 안). 파싱하지 않고 `shortage_events`에 원문 그대로 둔다. 날짜 문자열(MM/DD/YYYY)은 date로 바꾼다.

## 용어 정의 (평가 정답의 기준)
- **가용 재고**: `lot_status='available'` 이고 `expiry_date >= 기준일`(유통기한 당일은 유효)인 로트의 수량 합. 격리·만료 로트는 제외.
- **유통기한 N일 이내**: `기준일 <= expiry_date <= 기준일 + N일`(양 끝 포함).
- **안전재고 부족**: 가용 재고 < `products.safety_stock`(같으면 부족 아님). 안전재고는 최근 6개월 월평균 주문량 × U(0.8, 1.5), 100 단위 반올림, 하한 500.
- **기한 경과 미입고 발주**: `status='open'` 이고 `expected_date < 기준일`(당일은 경과 아님).
- **리드타임**: 입고 완료 발주의 `received_date - order_date`(일) 평균.
- **결품 상태**(성분명 단위, 포장 단위 NDC 여러 건을 묶는다): Current가 하나라도 있으면 **결품 중** → 없고 To Be Discontinued가 있으면 **단종 예정** → 없고 Resolved가 있으면 **해소됨** → 스냅샷에 없으면 **기록 없음**. ("단종 예정"은 지금 부족하다는 뜻이 아니다.)

## 의도적으로 심은 경계 사례 (`synth.lots`, `synth.purchase_orders`)
안전재고와 정확히 같은 SKU 3, 1 모자란 SKU 3, 가용 재고 0 SKU 3(+우연히 1), 유통기한 기준일 +0/+29/+30/+31/+60/+90/+91일 로트 각 1, 이미 만료된 로트(-1일, -30일), 격리 로트 4, 기한 경과 미입고 발주(의도적으로 12건 추가, 자연 발생분 포함 전체 17건), 예상일이 기준일과 같은 미입고 발주 2건(경과 아님).

## 한계
- DataCo는 2017년 중반부터 판매 제품 수가 줄어, 118개 중 73개만 마지막 6개월에 판다. 그 결과 **SKU 30개는 최근 6개월 수요가 0**이고 안전재고가 하한(500)이다. "느리게 팔리는 품목"으로 보지만 실제 약품 수요 분포가 아니다.
- 성분명 문자열로만 결품과 SKU를 잇는다. 같은 성분의 다른 제형·함량은 구분하지 않는다.
- 로트·발주는 SKU 90개에 각 1~4 로트, 8~16건 발주로 작다. 규모 검증용이 아니다.
- 합성 SOP 30개 섹션은 실제 GMP 규정이 아니다.

## 재현
```bash
docker compose up -d db
uv sync
uv run python -m pharma_scm.build            # 스키마 재생성 + 전체 적재(멱등)
uv run python -m pharma_scm.evalset.build_evalset
uv run pytest
```
`build`가 출력하는 표별 (행 수, md5)가 두 번 실행해 같음을 확인했다(2026-11-03). 출력 전체의 md5 = `7b886393ae983f064d4015b4b15d198e`.
