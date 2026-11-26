"""검색에 쓰는 모델 이름, 고정 리비전, 장치 선택, 내려받기(docs/rag_eval_results.md §1).

이 파일은 패키지의 다른 모듈을 가져오지 않는다. Docker 빌드가 소스 전체를 복사하기 전에 이 파일 하나만 실행해
모델을 받아 두므로(소스가 바뀌어도 모델 레이어는 캐시된다), 단독으로 실행할 수 있어야 한다.

    python src/pharma_scm/retrieval/models.py     # 임베딩 모델 내려받기(필요한 파일만)
"""

import os

DENSE_MODEL = "BAAI/bge-m3"
# 벤치마크(2026-11-26)에 쓴 리비전. 모델 저장소가 바뀌어도 같은 가중치를 쓰도록 고정한다.
DENSE_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"  # 벤치마크 R4 전용(운영에서는 쓰지 않는다)
# sentence-transformers가 쓰지 않는 파일(ONNX 변환본, 희소·ColBERT 헤드, 그림)은 받지 않는다.
SKIP_FILES = ["onnx/*", "*.pt", "*.jpg", "imgs/*", "README.md"]
# transformers는 .bin 가중치를 읽으면 백그라운드에서 safetensors 변환본(고정되지 않은 PR 리비전, 2.27GB)을
# 한 벌 더 받는다. 쓰지 않는 파일이고 이미지·CI 캐시를 두 배로 키우므로 끈다.
os.environ.setdefault("DISABLE_SAFETENSORS_CONVERSION", "1")


def pick_device():
    """GPU가 실제로 계산되는지 확인하고, 안 되면 CPU를 쓴다. PHARMA_DEVICE=cpu면 항상 CPU."""
    import torch

    if os.environ.get("PHARMA_DEVICE") == "cpu":
        return "cpu"
    if torch.cuda.is_available():
        try:
            torch.zeros(1, device="cuda") + 1
            return "cuda"
        except Exception as e:
            print(f"CUDA가 보이지만 계산에 실패해 CPU를 쓴다: {e}")
    return "cpu"


def download():
    from huggingface_hub import snapshot_download

    return snapshot_download(DENSE_MODEL, revision=DENSE_REVISION, ignore_patterns=SKIP_FILES)


def load_dense(device=None):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(DENSE_MODEL, revision=DENSE_REVISION, device=device or pick_device())


if __name__ == "__main__":
    print(f"{DENSE_MODEL}@{DENSE_REVISION[:8]} -> {download()}")
