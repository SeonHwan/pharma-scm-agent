"""검색 벤치마크 실행기: R0~R4를 질의 146개에 돌리고 사전 등록된 규칙으로 판정.

LLM API는 호출하지 않음. 사전 등록 순서상 이 실행은 한 번만 함: 결과 파일이 이미 있으면 멈추고, 코퍼스나 질의가
등록된 md5와 다르면 시작하지 않음. 결과를 본 뒤 코드를 바꿔 다시 돌리려면 그 사실과 이유를 문서에 적어야 함.

    uv run python -m pharma_scm.retrieval.run_benchmark
"""

import hashlib
import json
import platform
import statistics
import time
from datetime import datetime, timezone

from .. import config
from . import corpus, metrics, register
from .benchmark_data import load_benchmark
from .dense import DenseBgeM3
from .finalize_queries import FINAL
from .fusion import Rrf
from .methods import Bm25, TfidfCosine
from .models import DENSE_MODEL, RERANK_MODEL, load_dense, pick_device
from .rerank import Reranker

RESULT = config.ROOT / "eval" / "rag" / "benchmark_results.json"
WARMUP = 5  # 지연 측정에서 버리는 준비 호출 수(GPU 초기화, 캐시). 순위 결과에는 영향이 없음
CLASSES = {
    "전체": lambda it: True,
    "낮은 겹침": lambda it: it["low_overlap"],
    "높은 겹침": lambda it: not it["low_overlap"],
    "v1 문항": lambda it: it["source"] == "v1",
    "v2 질의": lambda it: it["source"] == "v2",
}


def check_registered():
    reg = json.loads(register.REGISTERED.read_text(encoding="utf-8"))
    if register.md5_map() != reg["corpus_md5"]:
        raise SystemExit("코퍼스가 등록된 md5와 다르다. 실행하지 않는다.")
    if hashlib.md5(FINAL.read_bytes()).hexdigest() != reg["queries_v2_final_md5"]:
        raise SystemExit("최종 질의가 등록된 md5와 다르다. 실행하지 않는다.")
    return reg


def timed(fn):
    started = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - started


def build(sections):
    """방식 5개를 만들고 구축 시간을 재서 돌려줌. 모델 로드는 색인 구축과 따로 측정."""
    from sentence_transformers import CrossEncoder

    device = pick_device()
    build_s, load_s = {}, {}
    r0, build_s["R0"] = timed(lambda: TfidfCosine(sections))
    r1, build_s["R1"] = timed(lambda: Bm25(sections))
    dense_model, load_s[DENSE_MODEL] = timed(lambda: load_dense(device))
    r2, build_s["R2"] = timed(lambda: DenseBgeM3(sections, model=dense_model))
    r3 = Rrf([r1, r2])  # 결합 자체는 색인이 없음(질의마다 R1, R2를 실행)
    cross, load_s[RERANK_MODEL] = timed(lambda: CrossEncoder(RERANK_MODEL, device=device))
    r4 = Reranker(sections, r3, model=cross)
    return [r0, r1, r2, r3, r4], build_s, load_s, device


def run_method(method, items):
    """질의마다 전체 순위를 구하고 걸린 시간(밀리초)을 측정. 준비 호출은 시간과 결과에서 모두 버림."""
    for it in items[:WARMUP]:
        method.rank(it["query"])
    rankings, ms = [], []
    for it in items:
        order, sec = timed(lambda it=it: method.rank(it["query"]))
        rankings.append(order)
        ms.append(sec * 1000)
    return rankings, ms


def report(items, results, build_s, load_s, decision):
    names = [m for m in results]
    for cls, pick in CLASSES.items():
        idx = [i for i, it in enumerate(items) if pick(it)]
        print(f"\n### {cls} (질의 {len(idx)}개)")
        print("| 방식 | recall@1 | recall@3 | MRR |")
        print("|---|---|---|---|")
        for m in names:
            s = metrics.summarize([results[m]["ranks"][i] for i in idx])
            lo1, hi1 = metrics.wilson(s["k1"], s["n"])
            lo3, hi3 = metrics.wilson(s["k3"], s["n"])
            print(f"| {m} | {s['k1'] / s['n']:.3f} [{lo1:.3f}, {hi1:.3f}] | "
                  f"{s['k3'] / s['n']:.3f} [{lo3:.3f}, {hi3:.3f}] | {s['mrr']:.3f} |")
    print("\n### 지연(질의당 밀리초)과 구축 시간")
    print("| 방식 | p50 | p95 | 구축(초) |")
    print("|---|---|---|---|")
    for m in names:
        ms = results[m]["ms"]
        print(f"| {m} | {statistics.median(ms):.1f} | {metrics.percentile(ms, 95):.1f} | "
              f"{build_s.get(m, 0):.3f} |")
    print("모델 로드(초): " + ", ".join(f"{k} {v:.1f}" for k, v in load_s.items()))
    print("\n### 사전 등록 규칙 §6 판정")
    b = decision["base_ci"]
    print(f"R0 낮은 겹침 recall@3 95% 구간 [{b[0]:.3f}, {b[1]:.3f}]")
    for name, d in decision["details"].items():
        print(f"{name}: 차이 {d['gain'] * 100:+.1f}%p(10%p 이상 {d['gain_ok']}), "
              f"구간 {d['ci'][0]:.3f}~{d['ci'][1]:.3f}가 R0 상한 밖 {d['ci_ok']}, "
              f"p95 {d['p95_ms']:.0f}ms(상한 {d['limit_ms']}ms) {d['latency_ok']} -> 통과 {d['pass']}")
    print(f"=> 결과: {decision['chosen']}" + (" (현재 방식 유지, 차이 없음)" if decision["chosen"] == "R0" else ""))


def main():
    if RESULT.exists():
        raise SystemExit(f"{RESULT.name}가 이미 있다. 사전 등록상 한 번만 실행한다(다시 돌리려면 이유를 문서에 적고 파일을 지운다).")
    reg = check_registered()
    items = load_benchmark()
    sections = corpus.load_corpus()
    methods, build_s, load_s, device = build(sections)
    results = {}
    for m in methods:
        rankings, ms = run_method(m, items)
        ranks = [order.index(it["gold"]) + 1 for order, it in zip(rankings, items)]
        results[m.name] = {"ranks": ranks, "ms": ms, "top3": [o[:3] for o in rankings]}
        print(f"{m.name} 완료", flush=True)
    low_idx = [i for i, it in enumerate(items) if it["low_overlap"]]
    low_stats = {m: metrics.summarize([results[m]["ranks"][i] for i in low_idx]) for m in results}
    p95 = {m: metrics.percentile(results[m]["ms"], 95) for m in results}
    decision = metrics.decide(low_stats, p95)
    report(items, results, build_s, load_s, decision)
    RESULT.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(), "device": device, "python": platform.python_version(),
        "registered": reg, "build_seconds": build_s, "model_load_seconds": load_s, "warmup_calls": WARMUP,
        "chosen": decision["chosen"],
        "queries": [{"id": it["id"], "gold": it["gold"], "source": it["source"], "overlap": it["overlap"],
                     "low_overlap": it["low_overlap"],
                     "methods": {m: {"rank": results[m]["ranks"][i], "top3": results[m]["top3"][i],
                                     "ms": round(results[m]["ms"][i], 2)} for m in results}}
                    for i, it in enumerate(items)],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n저장: {RESULT.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
