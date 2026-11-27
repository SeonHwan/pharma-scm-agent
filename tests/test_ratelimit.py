from pharma_scm.api.ratelimit import RateLimiter


def test_blocks_after_limit_and_recovers_after_window():
    """한도를 넘으면 막고 재시도 시간을 알려 주며, 시간 창이 지나면 다시 허용(비용 폭주 방지)."""
    t = [0.0]
    rl = RateLimiter(2, window_s=60, clock=lambda: t[0])
    assert rl.check("a")[0] and rl.check("a")[0]
    ok, retry = rl.check("a")
    assert not ok and 1 <= retry <= 61
    t[0] = 61
    assert rl.check("a")[0]
