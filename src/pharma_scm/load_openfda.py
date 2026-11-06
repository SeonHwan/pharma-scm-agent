"""openFDA 결품 스냅샷(JSON)을 shortage_events로 적재한다."""

import glob
import json
from datetime import datetime

from . import config

_COLS = [
    "package_ndc", "generic_name", "status", "dosage_form", "presentation", "company_name",
    "therapeutic_category", "initial_posting_date", "update_date", "discontinued_date",
    "update_type", "availability", "shortage_reason", "resolved_note", "related_info",
]


def _date(s):
    return datetime.strptime(s, "%m/%d/%Y").date() if s else None


def read_records():
    pattern = str(config.RAW_DIR / f"openfda_shortages_{config.SHORTAGE_SNAPSHOT}_*.json")
    files = sorted(glob.glob(pattern), key=lambda p: int(p.rsplit("_", 1)[1].split(".")[0]))
    records = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            records += json.load(fh)["results"]
    return records


def row(r):
    out = {c: r.get(c) for c in _COLS}
    out["therapeutic_category"] = "; ".join(r.get("therapeutic_category") or []) or None
    for c in ("initial_posting_date", "update_date", "discontinued_date"):
        out[c] = _date(out[c])
    return [out[c] for c in _COLS]


def load(conn):
    records = read_records()
    assert len(records) == 1622, f"스냅샷 건수 불일치: {len(records)}"
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO shortage_events ({', '.join(_COLS)}) "
            f"VALUES ({', '.join(['%s'] * len(_COLS))})",
            [row(r) for r in records],
        )
    return records
