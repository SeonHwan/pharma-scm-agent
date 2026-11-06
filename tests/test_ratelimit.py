from pharma_scm.api.ratelimit import RateLimiter


def test_blocks_after_limit_and_recovers_after_window():
    t = [0.0]
    rl = RateLimiter(2, window_s=60, clock=lambda: t[0])
    assert rl.check("a")[0] and rl.check("a")[0]
    ok, retry = rl.check("a")
    assert not ok and 1 <= retry <= 61
    t[0] = 61
    assert rl.check("a")[0]


def test_keys_are_independent():
    rl = RateLimiter(1, clock=lambda: 0.0)
    assert rl.check("a")[0] and rl.check("b")[0] and not rl.check("a")[0]
