"""밀집 임베딩 검색 R2(docs/rag_eval_protocol.md §4). 모델은 BAAI/bge-m3 하나로 고정한다.

색인 문서는 "제목 본문"(자연스러운 문장)이고, 질의에는 지시문 접두어를 붙이지 않는다(bge-m3 권장 사용법).
벡터는 길이 1로 정규화해 내적이 코사인 유사도가 되게 한다. sentence-transformers가 필요한 `retrieval` 의존성 그룹이
있어야 하므로 이 모듈을 가져올 때가 아니라 객체를 만들 때 라이브러리를 읽는다.

    uv run --group retrieval python ...
"""

from .corpus import section_text
from .embed_check import MODEL, pick_device
from .methods import rank_ids


class DenseBgeM3:
    """R2: 섹션과 질의를 bge-m3로 임베딩하고 내적으로 순위를 매긴다."""

    name = "R2"

    def __init__(self, sections, model=None):
        from sentence_transformers import SentenceTransformer

        self.ids = [s["section_id"] for s in sections]
        self.model = model or SentenceTransformer(MODEL, device=pick_device())
        self.vecs = self.model.encode([section_text(s) for s in sections], batch_size=16,
                                      normalize_embeddings=True, show_progress_bar=False)

    def scores(self, query):
        qv = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        return (self.vecs @ qv).tolist()

    def rank(self, query):
        return rank_ids(self.ids, self.scores(query))
