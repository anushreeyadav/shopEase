"""Edge controls applied before proxying: which routes are public, and per-client rate limits.

The gateway only *authenticates* (is the access token genuine and unexpired?). Services
verify the token again and do all authorization (ADR-05).
"""

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# (method, path pattern) pairs reachable without a token (rest_api_notes.md Part 5).
PUBLIC_ROUTES = [
    ("POST", re.compile(r"^/api/auth/(register|login|refresh)$")),
    ("GET", re.compile(r"^/api/auth/\.well-known/jwks\.json$")),
    ("GET", re.compile(r"^/api/products(/[^/]+)?$")),
    ("GET", re.compile(r"^/api/categories(/[^/]+)?$")),
    # Provider webhooks authenticate with the provider's signature, checked by payment_service.
    ("POST", re.compile(r"^/api/payments/webhooks/[^/]+$")),
]

# Credential endpoints get the strict limit: brute force and account-creation abuse.
AUTH_LIMITED = re.compile(r"^/api/auth/(register|login|refresh)$")


def is_public(method: str, path: str) -> bool:
    return any(method == m and pattern.match(path) for m, pattern in PUBLIC_ROUTES)


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class FixedWindowRateLimiter:
    """In-memory fixed-window counter per key.

    Per gateway process: with several gateway copies each keeps its own counts, so a shared
    store (e.g. Redis) is needed before scaling out.
    """

    def __init__(self, window_seconds: int = 60, clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window_seconds
        self.clock = clock
        self._counts: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> RateDecision:
        now = self.clock()
        with self._lock:
            start, count = self._counts.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._counts[key] = (start, count)
            if len(self._counts) > 10_000:
                self._counts = {k: v for k, v in self._counts.items() if now - v[0] < self.window}
        reset = max(1, int(start + self.window - now + 0.999))
        return RateDecision(count <= limit, limit, max(0, limit - count), reset)
