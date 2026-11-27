"""순위 결합 R3: 여러 검색 방식의 순위를 RRF(Reciprocal Rank Fusion)로 합침.

섹션의 점수 = 각 방식에서의 순위 r(1부터)에 대한 1 / (k + r)의 합. 점수는 크기가 다른 방식끼리도 순위만 쓰므로
점수를 정규화할 필요가 없음. k=60은 원 논문의 값이고 조정하지 않음. 같은 점수면 section_id 순.
각 방식의 전체 순위를 합치므로 한 방식에서 낮은 순위여도 다른 방식에서 높으면 위로 올라올 수 있음.
"""

from .methods import rank_ids

K = 60


class Rrf:
    """R3: 주어진 방식들의 순위를 RRF로 합침. 질의마다 각 방식을 실제로 실행(지연에 모두 포함)."""

    name = "R3"

    def __init__(self, methods, k=K):
        self.methods = methods
        self.k = k
        self.ids = methods[0].ids

    def scores(self, query):
        total = {i: 0.0 for i in self.ids}
        for m in self.methods:
            for r, sid in enumerate(m.rank(query), 1):
                total[sid] += 1.0 / (self.k + r)
        return [total[i] for i in self.ids]

    def rank(self, query):
        return rank_ids(self.ids, self.scores(query))
