import os

import pytest

from pharma_scm.retrieval import corpus
from pharma_scm.retrieval.methods import Bm25
from pharma_scm.retrieval.rerank import Reranker

# 실제 리랭커(약 2GB)를 내려받아 쓰는 시험은 RUN_MODEL_TESTS=1일 때만 돌린다(CI 기본은 건너뜀).
needs_model = pytest.mark.skipif(not os.environ.get("RUN_MODEL_TESTS"), reason="RUN_MODEL_TESTS=1일 때만 실행")


class FakeModel:
    """점수를 정해 둔 가짜 교차 인코더(재정렬과 꼬리 처리 로직만 시험한다)."""

    def __init__(self, by_text):
        self.by_text = by_text

    def predict(self, pairs, **kw):
        return [self.by_text.get(text, 0.0) for _q, text in pairs]


def test_rerank_reorders_head_and_keeps_tail():
    secs = corpus.load_corpus()
    base = Bm25(secs)
    query = "냉장 보관 온도 기록"
    order = base.rank(query)
    last_of_head = secs_by_id(secs)[order[4]]
    # 후보 5개 중 5위에 가장 높은 점수를 준다 -> 5위가 1위가 되고 나머지 순서는 유지된다.
    model = FakeModel({corpus.section_text(last_of_head): 1.0})
    r = Reranker(secs, base, model=model, top_n=5)
    got = r.rank(query)
    assert got[0] == order[4]
    assert got[1:5] == order[:4]
    assert got[5:] == order[5:]


@needs_model
def test_real_model_ranks_own_text_first():
    secs = corpus.load_corpus()
    base = Bm25(secs)
    r = Reranker(secs, base)
    for s in secs[::40]:
        got = r.rank(s["body"])
        assert got[0] == s["section_id"]
        assert sorted(got) == sorted(x["section_id"] for x in secs)


def secs_by_id(secs):
    return {s["section_id"]: s for s in secs}
