"""
Test-only default `Idempotency-Key` for in-process booking calls (pricing D3 / A-17).

`POST /api/v1/shipments` requires an `Idempotency-Key` header. The frontend always sends one;
the ~100 in-process API test clients predate the rule. `IdempotencyKeyDefaultMiddleware` adds a
fresh random key to a booking request that has none, so suites that are not about idempotency
keep testing what they test. Requests that carry their own key (replay / race tests) are left
untouched, and the contract test for "missing key -> 400" switches the default off with
`monkeypatch.setattr(idempotency_default, "INJECT_DEFAULT_KEY", False)`.

Spring analogy: a test-scope `ClientHttpRequestInterceptor` that adds a header.
"""

import uuid
from typing import Iterable, Tuple

from starlette.types import ASGIApp, Receive, Scope, Send

IDEMPOTENCY_HEADER = b"idempotency-key"
BOOKING_METHOD = "POST"
BOOKING_PATHS = frozenset({"/api/v1/shipments"})
INJECT_DEFAULT_KEY = True
"""Read at request time; the missing-key contract test sets it to False."""


def _has_header(headers: Iterable[Tuple[bytes, bytes]], name: bytes) -> bool:
    """True when the raw ASGI header list already holds `name` (case-insensitive)."""
    return any(key.lower() == name for key, _ in headers)


def needs_default_key(scope: Scope) -> bool:
    """True for a booking request without its own `Idempotency-Key` while injection is on."""
    return (
        INJECT_DEFAULT_KEY
        and scope.get("type") == "http"
        and scope.get("method") == BOOKING_METHOD
        and scope.get("path") in BOOKING_PATHS
        and not _has_header(scope.get("headers", []), IDEMPOTENCY_HEADER)
    )


class IdempotencyKeyDefaultMiddleware:
    """Pure ASGI middleware: adds `Idempotency-Key: golden-<uuid4>` to keyless booking calls."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if needs_default_key(scope):
            key = f"golden-{uuid.uuid4()}".encode()
            scope = {**scope, "headers": [*scope.get("headers", []), (IDEMPOTENCY_HEADER, key)]}
        await self.app(scope, receive, send)
