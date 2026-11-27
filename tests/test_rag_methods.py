# R0가 당시 운영 코드(run_search_sop)와 같은 순위·점수를 냈다는 확인은 커밋 14114b4의 테스트로 함.
# 운영 검색이 R3로 바뀐 뒤에는 R0는 벤치마크 기준선으로만 남음.

from pharma_scm.retrieval import corpus
from pharma_scm.retrieval.methods import Bm25, TfidfCosine


def test_bm25_ranks_own_text_first():
    secs = corpus.load_corpus()
    bm = Bm25(secs)
    for s in secs[::20]:
        assert bm.rank(s["body"])[0] == s["section_id"]


def test_rank_is_deterministic_and_complete():
    secs = corpus.load_corpus()
    for method in (TfidfCosine(secs), Bm25(secs)):
        a = method.rank("냉장 보관 온도")
        assert a == method.rank("냉장 보관 온도")
        assert sorted(a) == sorted(s["section_id"] for s in secs)
