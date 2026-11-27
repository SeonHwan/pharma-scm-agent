"""키별 슬라이딩 윈도 rate limit. 프로세스 메모리에만 있음(여러 프로세스 간 공유 안 됨)."""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests, window_s=60.0, clock=time.monotonic):
        self.max, self.window, self.clock = max_requests, window_s, clock
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key):
        """반환: (허용 여부, 재시도까지 남은 초)."""
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.max:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return True, 0
