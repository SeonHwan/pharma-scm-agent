"""재정렬 R4: R3 순위의 상위 20개를 교차 인코더 BAAI/bge-reranker-v2-m3로 다시 정렬한다(docs/rag_eval_protocol.md §4).

교차 인코더는 질의와 섹션을 한 쌍으로 모델에 넣어 관련도를 직접 계산한다(임베딩처럼 따로 벡터를 만들지 않는다).
정확도는 높을 수 있지만 쌍마다 모델을 돌려야 해서 후보 20개로 제한한다. 21위 이하는 리랭커가 보지 않으므로
R3의 순서를 그대로 뒤에 붙인다. 점수는 순위에만 쓰고, 같은 점수면 앞선 순위(R3 순서)를 유지한다.
"""

from .corpus import section_text
from .embed_check import pick_device

MODEL = "BAAI/bge-reranker-v2-m3"
TOP_N = 20


class Reranker:
    """R4: 후보 검색 방식(R3)의 상위 TOP_N개를 교차 인코더로 재정렬한다."""

    name = "R4"

    def __init__(self, sections, candidates, model=None, top_n=TOP_N):
        from sentence_transformers import CrossEncoder

        self.texts = {s["section_id"]: section_text(s) for s in sections}
        self.candidates = candidates
        self.top_n = top_n
        self.ids = candidates.ids
        self.model = model or CrossEncoder(MODEL, device=pick_device())

    def rank(self, query):
        order = self.candidates.rank(query)
        head, tail = order[:self.top_n], order[self.top_n:]
        scores = self.model.predict([(query, self.texts[i]) for i in head], batch_size=self.top_n,
                                    show_progress_bar=False)
        # 정렬은 안정적이므로 점수가 같으면 후보 순서(R3)가 유지된다.
        reranked = [i for _s, i in sorted(zip(scores, head), key=lambda t: -t[0])]
        return reranked + tail
