"""운영 규정 검색: sop/ 문서를 R3(BM25 + bge-m3 임베딩, RRF 결합)로 검색한다(docs/rag_eval_results.md §4, §8).

섹션 벡터는 빌드 때 한 번 계산해 파일로 저장하고(build), 서버는 시작할 때 읽기만 한다(load). 시작할 때 섹션을
임베딩하면 메모리 피크(약 2.5GB)와 시간(CPU에서 10초 이상)이 생기기 때문이다. 색인 파일에는 만들 때의 문서 md5가
들어 있어서 문서가 바뀌었는데 색인을 다시 만들지 않았으면 읽기를 거부한다.

    uv run python -m pharma_scm.retrieval.index      # 색인 빌드(모델이 없으면 내려받는다)
"""

import json
import os

import numpy as np

from .. import config
from .corpus import load_corpus, section_text
from .models import DENSE_MODEL, DENSE_REVISION, load_dense
from .fusion import Rrf
from .methods import Bm25, rank_ids
from .register import md5_map

INDEX_DIR = config.ROOT / "build" / "sop_index"
VECTORS = "vectors.npy"
META = "meta.json"


class PrecomputedDense:
    """미리 계산한 섹션 벡터와 질의 임베딩 함수로 순위를 매긴다(R2와 같은 계산)."""

    def __init__(self, ids, vectors, embed_query):
        self.ids = ids
        self.vectors = vectors
        self.embed_query = embed_query

    def rank(self, query):
        return rank_ids(self.ids, (self.vectors @ self.embed_query(query)).tolist())


class SopIndex:
    """규정 섹션 검색. search(질의, k)는 상위 k개 섹션을 돌려준다."""

    def __init__(self, sections, vectors, embed_query):
        ids = [s["section_id"] for s in sections]
        self.by_id = {s["section_id"]: s for s in sections}
        self.fused = Rrf([Bm25(sections), PrecomputedDense(ids, vectors, embed_query)])

    def search(self, query, k=3):
        scores = dict(zip(self.fused.ids, self.fused.scores(query)))
        out = []
        for sid in self.fused.rank(query)[:k]:
            s = self.by_id[sid]
            out.append({"section_id": sid, "doc_title": s["doc_title"], "title": s["title"],
                        "body": s["body"], "score": round(scores[sid], 4)})
        return out


def quantize_int8(model):
    """질의 임베딩용으로 Linear 층을 그 자리에서 int8 동적 양자화한다(docs/rag_eval_results.md §12).
    사본을 만들면 fp32 원본과 함께 메모리에 남아 약 5.8GB가 되므로 inplace로 바꾼다."""
    import warnings

    import torch

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # torch.ao.quantization 폐기 예정 경고(§12 한계에 적음)
        return torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)


def query_int8_enabled():
    """기본은 켠다(Fargate 1 vCPU p95 1358ms → 236ms, docs/rag_eval_results.md §13). PHARMA_QUERY_INT8=0이면 fp32."""
    return os.environ.get("PHARMA_QUERY_INT8", "1") != "0"


def model_embedder(int8=None):
    """bge-m3로 질의 하나를 정규화 벡터로 만드는 함수. 이미지에는 모델이 미리 들어 있다.
    int8이면 질의 쪽 모델만 양자화한다(섹션 벡터는 빌드 때의 fp32). 기본은 query_int8_enabled()."""
    model = load_dense("cpu")
    if int8 is None:
        int8 = query_int8_enabled()
    if int8:
        model = quantize_int8(model)
    return model, lambda q: model.encode([q], normalize_embeddings=True, show_progress_bar=False)[0]


def build(out_dir=INDEX_DIR):
    model, _ = model_embedder(int8=False)  # 섹션 벡터는 항상 fp32
    sections = load_corpus()
    vectors = model.encode([section_text(s) for s in sections], batch_size=16,
                           normalize_embeddings=True, show_progress_bar=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / VECTORS, vectors.astype(np.float32))
    (out_dir / META).write_text(json.dumps({
        "model": DENSE_MODEL, "revision": DENSE_REVISION,
        "section_ids": [s["section_id"] for s in sections], "corpus_md5": md5_map(),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(sections)


def load(index_dir=INDEX_DIR, embed_query=None):
    """색인 파일과 현재 sop/ 문서가 맞는지 확인하고 SopIndex를 만든다."""
    meta = json.loads((index_dir / META).read_text(encoding="utf-8"))
    sections = load_corpus()
    if meta["corpus_md5"] != md5_map() or meta["section_ids"] != [s["section_id"] for s in sections]:
        raise RuntimeError("sop/ 문서가 색인을 만든 뒤 바뀌었다. `python -m pharma_scm.retrieval.index`로 다시 만든다.")
    if embed_query is None:
        if (meta.get("model"), meta.get("revision")) != (DENSE_MODEL, DENSE_REVISION):
            raise RuntimeError("색인을 만든 모델이 지금 모델과 다르다. 색인을 다시 만든다.")
        _, embed_query = model_embedder()
    return SopIndex(sections, np.load(index_dir / VECTORS), embed_query)


def main():
    n = build()
    print(f"섹션 {n}개 색인 저장: {INDEX_DIR.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
