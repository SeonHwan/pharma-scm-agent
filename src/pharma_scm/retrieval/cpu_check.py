"""GPU 없는 환경(ECS Fargate)을 가정한 CPU 지연과 메모리 측정(4).

사전 등록 실행(run_benchmark)과는 별개의 "배포 환경 확인"이다. 같은 질의에 R2, R3, R4를 CPU로 돌려
(1) 질의당 지연을 스레드 수별로, (2) 모델을 올린 프로세스의 최대 메모리를, (3) GPU 실행과 순위가 같은지를 본다.
스레드 수는 Fargate vCPU 수의 근사일 뿐이다(vCPU는 시간을 나눠 쓰고 CPU 종류도 다르다). 0.5 vCPU는 1스레드보다
느릴 수 있다. LLM API는 호출하지 않는다.

    PHARMA_DEVICE=cpu uv run python -m pharma_scm.retrieval.cpu_check
"""

import argparse
import json
import os
import resource
import statistics
import time

from .. import config
from . import corpus, metrics
from .benchmark_data import load_benchmark
from .dense import DenseBgeM3
from .fusion import Rrf
from .methods import Bm25
from .models import RERANK_MODEL, load_dense, pick_device
from .rerank import Reranker
from .run_benchmark import RESULT, run_method

OUT = config.ROOT / "eval" / "rag" / "latency_cpu.json"


def peak_rss_mb():
    """프로세스가 지금까지 쓴 최대 상주 메모리(MB). 리눅스에서 ru_maxrss는 KB 단위다."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", default="16,4,2,1", help="측정할 torch 스레드 수(쉼표로 구분)")
    ap.add_argument("--every", type=int, default=3, help="질의를 every개마다 1개씩 쓴다(1이면 전부)")
    a = ap.parse_args()
    os.environ["PHARMA_DEVICE"] = "cpu"
    if pick_device() != "cpu":
        raise SystemExit("CPU로 고정되지 않았다")
    import torch
    from sentence_transformers import CrossEncoder

    items = load_benchmark()
    sample_idx = list(range(0, len(items), a.every))
    sample = [items[i] for i in sample_idx]
    sections = corpus.load_corpus()
    gpu = json.loads(RESULT.read_text(encoding="utf-8"))["queries"]

    mem = {"모델 올리기 전": peak_rss_mb()}
    dense_model = load_dense("cpu")
    mem["bge-m3 로드 후"] = peak_rss_mb()
    r1 = Bm25(sections)
    started = time.perf_counter()
    r2 = DenseBgeM3(sections, model=dense_model)
    index_s = time.perf_counter() - started
    mem["섹션 임베딩 후(R2 준비 끝)"] = peak_rss_mb()
    r3 = Rrf([r1, r2])
    cross = CrossEncoder(RERANK_MODEL, device="cpu")
    r4 = Reranker(sections, r3, model=cross)
    mem["리랭커 로드 후(R4 준비 끝)"] = peak_rss_mb()

    rows, agree = [], {}
    for n in [int(x) for x in a.threads.split(",")]:
        torch.set_num_threads(n)
        for m in (r2, r3, r4):
            rankings, ms = run_method(m, sample)
            rows.append({"threads": n, "method": m.name, "p50_ms": statistics.median(ms),
                         "p95_ms": metrics.percentile(ms, 95), "n": len(ms)})
            print(f"threads={n} {m.name} p50 {rows[-1]['p50_ms']:.1f}ms p95 {rows[-1]['p95_ms']:.1f}ms", flush=True)
            if n == int(a.threads.split(",")[0]):
                same_top1 = sum(o[0] == gpu[i]["methods"][m.name]["top3"][0] for o, i in zip(rankings, sample_idx))
                same_top3 = sum(o[:3] == gpu[i]["methods"][m.name]["top3"] for o, i in zip(rankings, sample_idx))
                agree[m.name] = {"top1_same": same_top1, "top3_same": same_top3, "n": len(sample)}

    print(f"\n질의 {len(sample)}개(전체 {len(items)}개 중 {a.every}개마다 1개), 장치 cpu, 코어 {os.cpu_count()}개")
    print("\n| 스레드 | 방식 | p50(ms) | p95(ms) |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r['threads']} | {r['method']} | {r['p50_ms']:.1f} | {r['p95_ms']:.1f} |")
    print(f"\nR2 색인(섹션 {len(sections)}개 임베딩) {index_s:.1f}초(스레드 {a.threads.split(',')[0]})")
    print("\n최대 메모리(MB, 프로세스 전체):")
    for k, v in mem.items():
        print(f"  {k}: {v:,.0f}")
    print("\nGPU 실행과 같은 순위인지(첫 스레드 설정에서 비교):")
    for k, v in agree.items():
        print(f"  {k}: 1위 같음 {v['top1_same']}/{v['n']}, 상위 3개 같음 {v['top3_same']}/{v['n']}")
    OUT.write_text(json.dumps({"every": a.every, "n": len(sample), "cores": os.cpu_count(), "rows": rows,
                               "peak_rss_mb": mem, "r2_index_seconds": index_s, "agreement_with_gpu": agree},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n저장: {OUT.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
