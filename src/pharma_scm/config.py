"""전역 상수. 기준일·시드·DB 접속은 여기서만 정한다."""

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SOP_DIR = ROOT / "sop"

# 평가 정답이 날짜에 따라 바뀌지 않도록 기준일을 고정한다.
AS_OF = date(2026, 11, 1)
SEED = 20261101

# openFDA 스냅샷 날짜(meta.last_updated). 파일명에도 들어 있다.
SHORTAGE_SNAPSHOT = "2026-11-02"

# DataCo 마지막 주문일(2018-01-31)이 기준일 하루 전이 되도록 옮긴다.
DATACO_LAST_ORDER = date(2018, 1, 31)
DATE_SHIFT_DAYS = (AS_OF - DATACO_LAST_ORDER).days - 1
# DataCo 수량(1~5)은 약품 단위로 작아서 박스 수로 환산한다.
QUANTITY_SCALE = 100

N_SKU_SHORTAGE = 80  # openFDA 성분명에서 뽑는 SKU 수
N_SKU_NO_RECORD = 10  # 결품 기록이 없는 SKU 수(음성 사례)

# 로컬 개발용 접속 정보(compose.yaml과 같다). 운영 값이 아니다.
ADMIN_DSN = os.environ.get(
    "PHARMA_ADMIN_DSN", "postgresql://pharma_admin:local-dev-only@localhost:5433/pharma"
)
RO_DSN = os.environ.get(
    "PHARMA_RO_DSN", "postgresql://pharma_ro:local-dev-only@localhost:5433/pharma"
)
EXT_DSN = os.environ.get(
    "PHARMA_EXT_DSN", "postgresql://pharma_ext:local-dev-only@localhost:5433/pharma"
)

AGENT_MODEL = "claude-sonnet-5-5"
JUDGE_MODEL = "gpt-5.6-terra"  # 채점 모델(P3에서 사용)


def load_env() -> None:
    """프로젝트 .env를 읽어 환경변수에 넣는다(값은 출력하지 않는다)."""
    from dotenv import dotenv_values

    vals = dotenv_values(ROOT / ".env")
    for k, v in vals.items():
        if v:
            os.environ[k] = v
