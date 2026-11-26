"""BAAI/bge-m3 임베딩 모델이 내려받아지고 동작하는지 확인한다(docs/rag_eval_protocol.md §9, R2 준비).

검색 벤치마크 전에 환경만 확인하는 시험이다. 코퍼스 섹션 몇 개와 질의 하나를 임베딩해 차원, 장치, 시간을 출력한다.
처음 실행하면 모델(약 2GB)을 내려받는다. LLM API는 호출하지 않는다.

    uv run --group retrieval python -m pharma_scm.retrieval.embed_check
"""

import time

from . import corpus

MODEL = "BAAI/bge-m3"


def pick_device():
    """GPU가 실제로 계산되는지 확인하고, 안 되면 CPU를 쓴다(최신 GPU는 PyTorch 빌드가 맞아야 한다)."""
    import torch

    if torch.cuda.is_available():
        try:
            torch.zeros(1, device="cuda") + 1
            return "cuda"
        except Exception as e:
            print(f"CUDA가 보이지만 계산에 실패해 CPU를 쓴다: {e}")
    return "cpu"


def main():
    from sentence_transformers import SentenceTransformer

    device = pick_device()
    print(f"장치: {device}")
    started = time.time()
    model = SentenceTransformer(MODEL, device=device)
    print(f"모델 로드 {time.time() - started:.1f}초(첫 실행이면 내려받는 시간 포함)")

    secs = corpus.load_corpus()[:8]
    texts = [f"{s['title']} {s['body']}" for s in secs]
    started = time.time()
    vecs = model.encode(texts, normalize_embeddings=True)
    print(f"섹션 {len(texts)}개 임베딩 {time.time() - started:.2f}초, 벡터 모양 {vecs.shape}")

    query = "보관 온도 기록은 얼마 동안 보관해야 하나요?"
    qv = model.encode([query], normalize_embeddings=True)[0]
    scores = vecs @ qv
    best = scores.argmax()
    print(f"질의: {query}")
    print(f"가장 가까운 섹션: {secs[best]['section_id']} {secs[best]['title']} (유사도 {scores[best]:.3f})")


if __name__ == "__main__":
    main()
