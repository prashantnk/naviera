"""
In-process rate limiting for the password auth endpoints (B-05).

Without it a script could brute-force logins, and every attempt runs bcrypt inside the single
shared database. The MVP runs ONE API process (DESIGN v4: one process for the Delhivery token
bucket too), so a small in-memory sliding window is enough and adds no dependency; move to a
shared store (Redis) if the API ever scales out.

Spring Boot Equivalent: a `HandlerInterceptor` backed by a Bucket4j in-memory bucket.
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status

from app.core.config import is_production
from app.schemas.v1.tenants import PasswordLoginRequest


SECONDS_PER_MINUTE = 60
FORWARDED_FOR_HEADER = "x-forwarded-for"
"""Render / Vercel put the real client IP first in this header."""
UNKNOWN_CLIENT = "unknown"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient", "test"})
"""Direct same-machine peers (uvicorn / httpx ASGITransport test clients)."""
MAX_TRACKED_KEYS = 20_000
"""Memory guard: when exceeded, keys with no hit inside their window are dropped."""


@dataclass(frozen=True)
class RateRule:
    """At most `max_hits` hits per `window_seconds` for one key."""

    max_hits: int
    window_seconds: int


LOGIN_PER_ACCOUNT = RateRule(max_hits=10, window_seconds=5 * SECONDS_PER_MINUTE)
LOGIN_PER_IP = RateRule(max_hits=30, window_seconds=5 * SECONDS_PER_MINUTE)
SIGNUP_PER_IP = RateRule(max_hits=5, window_seconds=60 * SECONDS_PER_MINUTE)


class SlidingWindowLimiter:
    """
    Thread-safe sliding-window counter per key (timestamps of recent hits).

    Args:
        clock: Monotonic seconds source (injectable for tests).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: Tuple[str, str], rule: RateRule) -> Optional[int]:
        """
        Records one attempt for `key`.

        Returns:
            None when allowed, else the whole seconds until the oldest hit leaves the window
            (the attempt is NOT recorded when refused, so waiting always helps).
        """
        now = self._clock()
        with self._lock:
            window = self._hits.setdefault(key, deque())
            self._evict(window, now, rule.window_seconds)
            if len(window) >= rule.max_hits:
                return max(1, math.ceil(window[0] + rule.window_seconds - now))
            window.append(now)
            if len(self._hits) > MAX_TRACKED_KEYS:
                self._prune(now, rule.window_seconds)
            return None

    def reset(self) -> None:
        """Forgets every key (tests)."""
        with self._lock:
            self._hits.clear()

    @staticmethod
    def _evict(window: Deque[float], now: float, window_seconds: int) -> None:
        """Drops hits older than the window."""
        while window and window[0] <= now - window_seconds:
            window.popleft()

    def _prune(self, now: float, window_seconds: int) -> None:
        """Removes keys whose hits all fell out of the window (memory guard)."""
        stale = [
            key for key, window in self._hits.items() if not window or window[-1] <= now - window_seconds
        ]
        for key in stale:
            del self._hits[key]


auth_limiter = SlidingWindowLimiter()
"""Process-wide limiter shared by the auth endpoints."""


def client_ip(request: Request) -> str:
    """The caller's IP: the first `X-Forwarded-For` entry behind a proxy, else the socket peer."""
    forwarded = request.headers.get(FORWARDED_FOR_HEADER, "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else UNKNOWN_CLIENT


def is_local_direct_call(request: Request) -> bool:
    """
    True for a same-machine caller (loopback client IP) outside production: local
    development and the golden test harness, which log in far more often than any human.
    Production is never exempt, so a spoofed `X-Forwarded-For: 127.0.0.1` gains nothing there.
    """
    if is_production():
        return False
    return client_ip(request) in LOOPBACK_HOSTS


def _too_many(retry_after: int) -> HTTPException:
    """429 with a plain-English message and a `Retry-After` header."""
    minutes = max(1, math.ceil(retry_after / SECONDS_PER_MINUTE))
    unit = "minute" if minutes == 1 else "minutes"
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many attempts. Please wait {minutes} {unit} and try again.",
        headers={"Retry-After": str(retry_after)},
    )


def _enforce(*checks: Tuple[Tuple[str, str], RateRule]) -> None:
    """Applies each (key, rule); the first refusal raises 429."""
    for key, rule in checks:
        retry_after = auth_limiter.hit(key, rule)
        if retry_after is not None:
            raise _too_many(retry_after)


def guard_login(request: Request, payload: PasswordLoginRequest) -> None:
    """FastAPI dependency: per-account and per-IP login limits."""
    if is_local_direct_call(request):
        return
    ip = client_ip(request)
    account = (payload.email or "").strip().lower()
    _enforce((("login-ip", ip), LOGIN_PER_IP), (("login-account", account), LOGIN_PER_ACCOUNT))


def guard_signup(request: Request) -> None:
    """FastAPI dependency: per-IP signup limit (accounts are cheap to create otherwise)."""
    if is_local_direct_call(request):
        return
    _enforce((("signup-ip", client_ip(request)), SIGNUP_PER_IP))
