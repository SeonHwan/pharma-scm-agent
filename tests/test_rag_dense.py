import pytest

# retrieval 의존성 그룹이 없는 환경(운영 이미지, CI)에서는 건너뛴다.
pytest.importorskip("sentence_transformers")

from pharma_scm.retrieval import corpus  # noqa: E402
from pharma_scm.retrieval.dense import DenseBgeM3  # noqa: E402


@pytest.fixture(scope="module")
def dense():
    return DenseBgeM3(corpus.load_corpus())


def test_dense_ranks_own_text_first(dense):
    secs = corpus.load_corpus()
    for s in secs[::25]:
        assert dense.rank(corpus.section_text(s))[0] == s["section_id"]


def test_dense_rank_is_complete_and_deterministic(dense):
    secs = corpus.load_corpus()
    a = dense.rank("냉장 보관 온도 기록")
    assert a == dense.rank("냉장 보관 온도 기록")
    assert sorted(a) == sorted(s["section_id"] for s in secs)
