"""
Simple login protection.

Counts FAILED logins per (IP address + email). After too many failures in
the time window, further attempts get "429 Too Many Requests" until the
oldest failure leaves the window. A successful login clears the counter.

Kept in memory: fine for one server. For several servers later, the same
interface can be backed by Redis without changing any other code.
"""
import math
import threading
import time
from collections import defaultdict, deque

from app.core.config import settings
from app.core.exceptions import TooManyRequestsError


class LoginRateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def key(ip: str | None, email: str) -> str:
        return f"{ip or 'unknown'}|{email.strip().lower()}"

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] >= self.window:
            q.popleft()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._failures.get(key)
            if not q:
                return
            self._prune(q, now)
            if len(q) >= self.max_attempts:
                retry_after = max(1, math.ceil(self.window - (now - q[0])))
                raise TooManyRequestsError(
                    f"Too many failed login attempts. Try again in {math.ceil(retry_after / 60)} minute(s).",
                    code="TOO_MANY_LOGIN_ATTEMPTS",
                    headers={"Retry-After": str(retry_after)},
                )

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginRateLimiter(settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_WINDOW_MINUTES * 60)
