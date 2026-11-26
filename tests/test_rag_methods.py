import json

import psycopg

from pharma_scm.agent import tools
from pharma_scm.retrieval import corpus
from pharma_scm.retrieval.benchmark_data import load_v1
from pharma_scm.retrieval.methods import Bm25, TfidfCosine


class FakeConn:
    """운영 색인이 읽는 sop_sections 테이블을 코퍼스 섹션으로 대신한다."""

    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        return self

    def fetchall(self):
        return self.rows


def original_sections():
    return [s for s in corpus.load_corpus() if int(s["doc_id"].split("-")[1]) <= 10]


def test_r0_matches_production_search(monkeypatch):
    # 벤치마크의 R0가 운영 코드(run_search_sop)와 같은 순위와 점수를 내야 비교 기준이 의미가 있다.
    secs = original_sections()
    assert len(secs) == 30
    rows = [(s["section_id"], s["doc_title"], s["title"], s["body"]) for s in secs]
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: FakeConn(rows))
    tools._sop_index.cache_clear()
    try:
        r0 = TfidfCosine(secs)
        for item in load_v1():
            prod = json.loads(tools.run_search_sop(item["query"], k=3))["results"]
            mine = r0.rank(item["query"])[:3]
            assert [p["section_id"] for p in prod] == mine, item["id"]
            scores = dict(zip(r0.ids, r0.scores(item["query"])))
            assert [p["score"] for p in prod] == [round(scores[i], 3) for i in mine], item["id"]
    finally:
        tools._sop_index.cache_clear()


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
