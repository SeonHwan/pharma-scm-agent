"""검색 벤치마크 질의(최종 v2 126개 + 기존 규정 문항 20개)를 읽고 어휘 겹침 부류를 나눈다(docs/rag_eval_protocol.md §3).

부류 규칙은 사전 등록된 대로다: 겹침 비율이 전체 질의의 중앙값 이하면 낮은 겹침, 나머지는 높은 겹침.
기존 규정 문항은 v1 문항으로 따로 표시한다(부류 계산에는 함께 들어간다).

    uv run python -m pharma_scm.retrieval.benchmark_data     # 개수와 부류 분포 출력
"""

import json
import statistics

from .. import config
from . import corpus
from .finalize_queries import FINAL

QUESTIONS = config.ROOT / "eval" / "questions.jsonl"


def load_v1(by_id):
    """eval/questions.jsonl의 규정 문항(C001~C020). 정답 섹션이 하나인 문항만 있다."""
    out = []
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["type"] != "C":
            continue
        assert r["gold"]["kind"] == "sections" and "," not in r["gold"]["value"], r["id"]
        out.append({"id": r["id"], "query": r["question"], "gold": r["gold"]["value"], "source": "v1"})
    return out


def load_v2():
    rows = [json.loads(line) for line in FINAL.read_text(encoding="utf-8").splitlines() if line]
    return [{"id": r["section_id"], "query": r["query"], "gold": r["section_id"], "source": "v2"} for r in rows]


def load_benchmark():
    """질의 목록. 항목: id, query, gold(정답 섹션 id), source(v1/v2), overlap, low_overlap."""
    by_id = {s["section_id"]: s for s in corpus.load_corpus()}
    items = load_v1(by_id) + load_v2()
    for it in items:
        it["overlap"] = corpus.overlap(it["query"], by_id[it["gold"]])
    median = statistics.median(it["overlap"] for it in items)
    for it in items:
        it["low_overlap"] = it["overlap"] <= median
    return items


def main():
    items = load_benchmark()
    median = statistics.median(it["overlap"] for it in items)
    low = [it for it in items if it["low_overlap"]]
    print(f"질의 {len(items)}개 (v1 {sum(it['source'] == 'v1' for it in items)} + v2 {sum(it['source'] == 'v2' for it in items)})")
    print(f"겹침 비율 중앙값 {median:.4f} -> 낮은 겹침 {len(low)}개, 높은 겹침 {len(items) - len(low)}개")
    for src in ("v1", "v2"):
        sub = [it for it in items if it["source"] == src]
        print(f"  {src}: 평균 겹침 {statistics.mean(it['overlap'] for it in sub):.3f}, "
              f"낮은 겹침 {sum(it['low_overlap'] for it in sub)}개 / {len(sub)}개")


if __name__ == "__main__":
    main()
