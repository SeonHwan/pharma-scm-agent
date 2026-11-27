import pytest

from pharma_scm.retrieval import corpus
from pharma_scm.retrieval.fusion import Rrf
from pharma_scm.retrieval.methods import Bm25, TfidfCosine


class Fixed:
    """항상 정해진 순위를 돌려주는 가짜 검색 방식(모델 없이 결합 계산만 시험)."""

    def __init__(self, order):
        self.order = order
        self.ids = sorted(order)

    def rank(self, query):
        return self.order


def test_rrf_scores_match_formula():
    a = Fixed(["x", "y", "z"])
    b = Fixed(["y", "z", "x"])
    r = Rrf([a, b], k=60)
    got = dict(zip(r.ids, r.scores("q")))
    assert got["x"] == pytest.approx(1 / 61 + 1 / 63)
    assert got["y"] == pytest.approx(1 / 62 + 1 / 61)
    assert got["z"] == pytest.approx(1 / 63 + 1 / 62)
    assert r.rank("q") == ["y", "x", "z"]


def test_rrf_ties_break_by_section_id():
    # 두 방식이 서로 반대 순서면 점수가 같고, 이때는 id 순이어야 결과가 결정적.
    r = Rrf([Fixed(["b", "a"]), Fixed(["a", "b"])])
    assert r.rank("q") == ["a", "b"]


def test_rrf_single_method_keeps_its_order():
    order = ["c", "a", "b"]
    assert Rrf([Fixed(order)]).rank("q") == order


def test_rrf_over_lexical_methods_is_complete():
    secs = corpus.load_corpus()
    r = Rrf([TfidfCosine(secs), Bm25(secs)])
    ranked = r.rank("냉장 보관 온도 기록")
    assert sorted(ranked) == sorted(s["section_id"] for s in secs)
    assert ranked == r.rank("냉장 보관 온도 기록")
