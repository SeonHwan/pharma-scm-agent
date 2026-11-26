"""밀집 임베딩 검색 R2(docs/rag_eval_protocol.md §4). 모델은 BAAI/bge-m3 하나로 고정한다.

색인 문서는 "제목 본문"(자연스러운 문장)이고, 질의에는 지시문 접두어를 붙이지 않는다(bge-m3 권장 사용법).
벡터는 길이 1로 정규화해 내적이 코사인 유사도가 되게 한다. sentence-transformers는 객체를 만들 때 읽는다(모듈을 가져오기만 할 때는 읽지 않는다).

    uv run python ...
"""

from .corpus import section_text
from .models import load_dense
from .methods import rank_ids


class DenseBgeM3:
    """R2: 섹션과 질의를 bge-m3로 임베딩하고 내적으로 순위를 매긴다."""

    name = "R2"

    def __init__(self, sections, model=None):
        self.ids = [s["section_id"] for s in sections]
        self.model = model or load_dense()
        self.vecs = self.model.encode([section_text(s) for s in sections], batch_size=16,
                                      normalize_embeddings=True, show_progress_bar=False)

    def scores(self, query):
        qv = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        return (self.vecs @ qv).tolist()

    def rank(self, query):
        return rank_ids(self.ids, self.scores(query))
