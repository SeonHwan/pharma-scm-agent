"""어휘 기반 검색 방식 R0(현재 방식)과 R1(BM25).

두 방식 모두 검색 단위는 섹션이고, 토큰은 공백을 없앤 소문자 글자 2-gram이다. 색인 문서는 운영 코드와 같이
"제목 제목 본문"(제목을 두 번 넣어 가중)으로 만든다. 순위는 점수 내림차순이고 같으면 section_id 순이다.

BM25 매개변수는 결과를 보기 전에 널리 쓰는 기본값(k1=1.5, b=0.75)으로 고정했고 조정하지 않는다.
질의 토큰은 중복을 없애 한 번씩만 센다.
"""

import math
from collections import Counter

from .corpus import grams


def index_text(sec):
    return f"{sec['title']} {sec['title']} {sec['body']}"


class TfidfCosine:
    """R0: agent/tools.py의 run_search_sop와 같은 계산(TF x IDF 벡터의 코사인 유사도)."""

    name = "R0"

    def __init__(self, sections):
        self.ids = [s["section_id"] for s in sections]
        docs = [Counter(grams(index_text(s))) for s in sections]
        df = Counter(g for c in docs for g in c)
        n = len(docs)
        self.idf = {g: math.log((n + 1) / (d + 1)) + 1 for g, d in df.items()}
        self.vecs = []
        for c in docs:
            v = {g: tf * self.idf[g] for g, tf in c.items()}
            self.vecs.append((v, math.sqrt(sum(x * x for x in v.values()))))

    def scores(self, query):
        qv = {g: tf * self.idf.get(g, 0.0) for g, tf in Counter(grams(query)).items()}
        qn = math.sqrt(sum(x * x for x in qv.values())) or 1.0
        return [sum(w * v.get(g, 0.0) for g, w in qv.items()) / (qn * vn) if vn else 0.0
                for v, vn in self.vecs]

    def rank(self, query):
        return rank_ids(self.ids, self.scores(query))


class Bm25:
    """R1: 같은 글자 2-gram 토큰에 BM25(idf = ln(1 + (N-df+0.5)/(df+0.5)))."""

    name = "R1"
    K1 = 1.5
    B = 0.75

    def __init__(self, sections):
        self.ids = [s["section_id"] for s in sections]
        self.tfs = [Counter(grams(index_text(s))) for s in sections]
        self.lens = [sum(c.values()) for c in self.tfs]
        self.avg_len = sum(self.lens) / len(self.lens)
        df = Counter(g for c in self.tfs for g in c)
        n = len(self.tfs)
        self.idf = {g: math.log(1 + (n - d + 0.5) / (d + 0.5)) for g, d in df.items()}

    def scores(self, query):
        terms = [g for g in set(grams(query)) if g in self.idf]
        out = []
        for tf, length in zip(self.tfs, self.lens):
            norm = self.K1 * (1 - self.B + self.B * length / self.avg_len)
            out.append(sum(self.idf[g] * tf[g] * (self.K1 + 1) / (tf[g] + norm) for g in terms if g in tf))
        return out

    def rank(self, query):
        return rank_ids(self.ids, self.scores(query))


def rank_ids(ids, scores):
    """점수 내림차순, 같으면 section_id 순으로 정렬한 id 목록."""
    return [i for _s, i in sorted(zip(scores, ids), key=lambda t: (-t[0], t[1]))]
