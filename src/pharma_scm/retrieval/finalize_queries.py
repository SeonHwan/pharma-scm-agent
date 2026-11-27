"""사용자 검토에서 X로 판정된 질의를 제외해 최종 질의 파일을 만들고 md5를 등록한다.

원본(queries_v2.jsonl)은 그대로 두고, 제외한 질의와 이유는 review_v2.jsonl에 남아 있다. 이 명령은 검색 방식을 한 번도
실행하기 전에 한 번만 쓰고, 이후에는 질의 셋을 바꾸지 않는다.

    uv run python -m pharma_scm.retrieval.finalize_queries
"""

import hashlib
import json

from .. import config
from .register import REGISTERED

RAG = config.ROOT / "eval" / "rag"
FINAL = RAG / "queries_v2_final.jsonl"


def load(name):
    return [json.loads(line) for line in (RAG / name).read_text(encoding="utf-8").splitlines() if line]


def main():
    queries = load("queries_v2.jsonl")
    excluded = {r["section_id"] for r in load("review_v2.jsonl") if r["judgment"] == "X"}
    kept = [q for q in queries if q["section_id"] not in excluded]
    FINAL.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in kept), encoding="utf-8")
    data = json.loads(REGISTERED.read_text(encoding="utf-8"))
    data["queries_v2_final_md5"] = hashlib.md5(FINAL.read_bytes()).hexdigest()
    data["queries_v2_final_count"] = len(kept)
    REGISTERED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"원본 {len(queries)}개 - 제외 {len(excluded)}개({', '.join(sorted(excluded))}) = 최종 {len(kept)}개")
    print(f"md5 등록: {data['queries_v2_final_md5']}")


if __name__ == "__main__":
    main()
