import pytest

from pharma_scm.retrieval import metrics


def test_wilson_known_values():
    lo, hi = metrics.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3)
    assert hi == pytest.approx(0.7634, abs=1e-3)
    lo, hi = metrics.wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-9)
    assert hi == pytest.approx(0.2775, abs=1e-3)
    assert metrics.wilson(0, 0) == (0.0, 0.0)


def test_summarize():
    s = metrics.summarize([1, 2, 3, 4, 10])
    assert (s["n"], s["k1"], s["k3"]) == (5, 1, 3)
    assert s["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 3 + 1 / 4 + 1 / 10) / 5)


def test_percentile_nearest_rank():
    v = list(range(1, 101))
    assert metrics.percentile(v, 50) == 50
    assert metrics.percentile(v, 95) == 95
    assert metrics.percentile([7], 95) == 7


def stat(k3, n=74):
    return {"n": n, "k1": 0, "k3": k3, "mrr": 0.0}


FAST = {"R3": 500, "R4": 900}


def test_decide_adopts_only_when_gain_and_intervals_and_latency_hold():
    # R0 20/74, R3 60/74: 차이가 크고 구간이 겹치지 않는다 -> R3
    low = {"R0": stat(20), "R3": stat(60), "R4": stat(70)}
    r = metrics.decide(low, FAST)
    assert r["chosen"] == "R3"  # 둘 다 통과하면 더 단순한 R3


def test_decide_keeps_r0_when_intervals_overlap():
    # 10%p 이상 높아도(40 vs 48 -> +10.8%p) 구간이 겹치면 채택하지 않는다
    low = {"R0": stat(40), "R3": stat(48), "R4": stat(49)}
    r = metrics.decide(low, FAST)
    assert r["details"]["R3"]["gain_ok"] and not r["details"]["R3"]["ci_ok"]
    assert r["chosen"] == "R0"


def test_decide_latency_blocks_adoption():
    low = {"R0": stat(20), "R3": stat(60), "R4": stat(70)}
    r = metrics.decide(low, {"R3": 1200, "R4": 900})
    assert not r["details"]["R3"]["latency_ok"]
    assert r["chosen"] == "R4"
    r = metrics.decide(low, {"R3": 1200, "R4": 2500})
    assert r["chosen"] == "R0"
