import os

import pytest

# 실제 모델(각 약 2GB)을 내려받아 쓰는 시험이라 RUN_MODEL_TESTS=1일 때만 돌림(CI 기본은 건너뜀).
if not os.environ.get("RUN_MODEL_TESTS"):
    pytest.skip("RUN_MODEL_TESTS=1일 때만 실행", allow_module_level=True)

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
