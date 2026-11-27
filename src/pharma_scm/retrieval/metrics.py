"""검색 벤치마크의 지표 계산과 사전 등록된 채택 규칙.

모델이나 파일을 읽지 않는 순수 계산이라 작은 가짜 데이터로 시험할 수 있음.
"""

import math

Z95 = 1.96
GAIN_PP = 0.10  # 낮은 겹침 recall@3이 R0보다 10%p 이상 높아야 함
P95_LIMIT_MS = {"R3": 1000, "R4": 2000}  # 질의당 p95 지연 상한(밀리초)


def wilson(k, n, z=Z95):
    """비율 k/n의 Wilson 95% 구간(하한, 상한). n이 0이면 (0, 0)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return center - half, center + half


def percentile(values, q):
    """가장 가까운 순위 방식의 백분위수(q는 0~100)."""
    s = sorted(values)
    return s[max(0, math.ceil(q / 100 * len(s)) - 1)]


def summarize(ranks):
    """정답 섹션의 순위(1부터) 목록에서 recall@1, recall@3(개수), MRR을 만듦."""
    n = len(ranks)
    return {"n": n, "k1": sum(r <= 1 for r in ranks), "k3": sum(r <= 3 for r in ranks),
            "mrr": sum(1 / r for r in ranks) / n if n else 0.0}


def recall3(stat):
    return stat["k3"] / stat["n"] if stat["n"] else 0.0


def decide(low_stats, p95_ms):
    """사전 등록 규칙 §6. low_stats: {방식: 낮은 겹침 부류 summarize 결과}, p95_ms: {방식: 지연 p95}.

    후보 R3, R4 각각이 (1) R0보다 낮은 겹침 recall@3이 10%p 이상 높고 두 Wilson 구간이 겹치지 않으며
    (2) p95 지연이 상한 미만이어야 채택 후보. 둘 다 통과하면 더 단순한 R3, 하나도 없으면 R0를 유지.
    """
    base = low_stats["R0"]
    base_lo, base_hi = wilson(base["k3"], base["n"])
    details = {}
    for name, limit in P95_LIMIT_MS.items():
        s = low_stats[name]
        lo, hi = wilson(s["k3"], s["n"])
        details[name] = {
            "gain": recall3(s) - recall3(base),
            "gain_ok": recall3(s) - recall3(base) >= GAIN_PP - 1e-12,
            "ci_ok": lo > base_hi,
            "latency_ok": p95_ms[name] < limit,
            "ci": (lo, hi), "p95_ms": p95_ms[name], "limit_ms": limit,
        }
        details[name]["pass"] = details[name]["gain_ok"] and details[name]["ci_ok"] and details[name]["latency_ok"]
    chosen = next((n for n in ("R3", "R4") if details[n]["pass"]), "R0")
    return {"chosen": chosen, "base_ci": (base_lo, base_hi), "details": details}
