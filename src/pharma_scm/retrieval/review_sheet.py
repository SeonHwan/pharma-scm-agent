"""사용자 확인 샘플 20개의 검토지를 만든다.

샘플 = 표시된 질의 전부(검증기가 정답과 다른 집합을 골랐거나, 정답과 같아도 메모를 단 것) + 나머지에서 시드 고정 난수로
뽑은 질의로 20개를 채운다. 표시 여부가 검토에 영향을 주지 않도록 순서는 섞는다. 검토지는 eval/rag/review_sheet_v2.md,
뽑힌 목록은 eval/rag/review_sample_v2.json에 남긴다(같은 규칙이면 같은 결과가 나온다).

    uv run python -m pharma_scm.retrieval.review_sheet
"""

import json
import random

from .. import config
from . import corpus

SEED = 20261126
SAMPLE_SIZE = 20
RAG = config.ROOT / "eval" / "rag"


def load(name):
    return [json.loads(line) for line in (RAG / name).read_text(encoding="utf-8").splitlines() if line]


def is_flagged(v):
    return v["agreement"] != "일치" or bool(v["verifier_note"].strip())


def pick(verifications):
    flagged = [v for v in verifications if is_flagged(v)]
    rest = [v for v in verifications if not is_flagged(v)]
    random.Random(SEED).shuffle(rest)
    chosen = flagged + rest[:max(0, SAMPLE_SIZE - len(flagged))]
    random.Random(SEED + 1).shuffle(chosen)
    return chosen, {v["section_id"] for v in flagged}


def render(chosen, queries, by_id):
    q_by_sec = {q["section_id"]: q for q in queries}
    out = ["# 질의 확인 검토지 (사용자 확인 샘플 20개)", "",
           "각 항목에서 **정답 섹션 하나만** 그 질의에 답할 수 있는지 봐 주세요.", "",
           "- **O**: 정답 섹션 하나만 질문에 답한다(다른 섹션은 답이 되지 않는다).",
           "- **X**: 다른 섹션도 답이 되거나, 질의가 무엇을 묻는지 불분명하거나, 정답 섹션에 근거가 없다.", "",
           "판정 결과는 X인 번호만 알려 주시면 됩니다(이유가 있으면 한 줄). 순서는 섞었고 표시 여부는 적지 않았습니다.", ""]
    for n, v in enumerate(chosen, 1):
        sid = v["section_id"]
        q = q_by_sec[sid]
        gold = by_id[sid]
        out += [f"## {n}. {sid}", "", f"**질의**: {v['query']}", "",
                f"**정답 섹션(질의를 만들 때의 의도)** {sid} {gold['title']}: {gold['body']}", "",
                f"**질의가 묻는 사실(생성 모델의 기록)**: {q['fact']}", ""]
        others = [s for s in v["verifier_sections"] if s != sid]
        picked = ", ".join(v["verifier_sections"]) or "없음"
        out.append(f"**다른 회사 모델이 고른 섹션**: {picked}")
        for s in others:
            out.append(f"- {s} {by_id[s]['title']}: {by_id[s]['body']}")
        if v["verifier_note"].strip():
            out.append(f"- 그 모델의 메모: {v['verifier_note']}")
        out += ["", "**판정**: (O / X)", "", "---", ""]
    return "\n".join(out)


def main():
    verifications = load("verification_v2.jsonl")
    queries = load("queries_v2.jsonl")
    by_id = {s["section_id"]: s for s in corpus.load_corpus()}
    chosen, flagged_ids = pick(verifications)
    (RAG / "review_sheet_v2.md").write_text(render(chosen, queries, by_id), encoding="utf-8")
    (RAG / "review_sample_v2.json").write_text(json.dumps({
        "seed": SEED, "flagged": sorted(flagged_ids),
        "sample": [v["section_id"] for v in chosen]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"표시된 질의 {len(flagged_ids)}개 + 무작위 {len(chosen) - len(flagged_ids)}개 = 샘플 {len(chosen)}개")
    print("검토지: eval/rag/review_sheet_v2.md")


if __name__ == "__main__":
    main()
