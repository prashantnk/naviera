"""
Test-only response audit: server-only pricing fields must never leave the API (pricing
DESIGN.md v4 §C.2 / D8, red-team finding 1 "margin leak").

`ResponseAuditMiddleware` wraps the in-process FastAPI app used by every API / golden suite
(`ASGITransport(app=app)`). It buffers each JSON response, walks every key and raises
`AssertionError` (the request then fails inside the test that made it) when it finds:

- `carrier_cost` or `gross` anywhere: what Delhivery / the transporter charges Logismart;
- `markup_percent` or `transporter_name` outside the staff-only pricing endpoints
  (`STAFF_PRICING_PATHS`): the margin and the internal partner names.

Registered once by `scripts/tests/conftest.py` before the app serves its first request.
Spring analogy: a test-scope `OncePerRequestFilter` that inspects every response body.
"""

import base64
import json
import re
from typing import Any, Iterator, Pattern, Sequence, Tuple

from starlette.types import ASGIApp, Message, Receive, Scope, Send

ALWAYS_FORBIDDEN_KEYS = frozenset({"carrier_cost", "gross"})
"""Never in any response, staff included (server-only columns)."""
CUSTOMER_FORBIDDEN_KEYS = frozenset({"markup_percent", "transporter_name"})
"""Only the staff pricing screens may return these."""
STAFF_PRICING_PATHS: Sequence[Pattern[str]] = (
    re.compile(r"^/api/v1/pricing/"),
    re.compile(r"^/api/v1/shipments/[^/]+/carrier-billing$"),
)
"""Staff-only pricing endpoints (pricing policy, Prime lanes, ops carrier billing; API_CONTRACT.md)."""
STAFF_SHIPMENT_PATHS: Sequence[Pattern[str]] = (
    re.compile(r"^/api/v1/shipments(?:/|$)"),
)
"""Shipment endpoints where staff (never customers) may receive `transporter_name` (#540 item 3)."""
STAFF_EMAIL_PREFIXES: Tuple[str, ...] = (
    "owner@",
    "admin@",
    "operations@",
    "support@",
    "readonly@",
)
JSON_CONTENT_TYPE = b"application/json"


def iter_keys(payload: Any, path: str = "$") -> Iterator[Tuple[str, str]]:
    """Yields (json-path, key) for every non-null object key in a decoded JSON document."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if value is not None:
                yield child, str(key)
            yield from iter_keys(value, child)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from iter_keys(item, f"{path}[{index}]")


def forbidden_keys(
    payload: Any, request_path: str, *, is_staff_caller: bool = False
) -> list[str]:
    """JSON paths of every forbidden key in `payload` for a response to `request_path`."""
    is_staff_pricing = any(p.search(request_path) for p in STAFF_PRICING_PATHS)
    is_staff_shipment = is_staff_caller and any(
        p.search(request_path) for p in STAFF_SHIPMENT_PATHS
    )
    customer_forbidden = (
        frozenset()
        if is_staff_pricing
        else (CUSTOMER_FORBIDDEN_KEYS - {"transporter_name"} if is_staff_shipment else CUSTOMER_FORBIDDEN_KEYS)
    )
    forbidden = ALWAYS_FORBIDDEN_KEYS | customer_forbidden
    return [path for path, key in iter_keys(payload) if key in forbidden]


class ResponseAuditMiddleware:
    """Pure ASGI middleware: fails the request when a JSON body leaks a server-only field."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start: list[Message] = []
        body = bytearray()
        staff_caller = _is_staff_scope(scope)

        async def audited_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                if not _is_json(message):
                    await send(message)
                    return
                start.append(message)  # held back until the whole JSON body is audited
                return
            if not start or message["type"] != "http.response.body":
                await send(message)
                return
            body.extend(message.get("body", b""))
            if message.get("more_body", False):
                return
            _audit(bytes(body), scope.get("path", ""), is_staff_caller=staff_caller)
            await send(start[0])
            await send({"type": "http.response.body", "body": bytes(body), "more_body": False})

        await self.app(scope, receive, audited_send)


def _is_json(start: Message) -> bool:
    """True when the response start message declares a JSON body."""
    headers = dict(start.get("headers", []))
    return headers.get(b"content-type", b"").startswith(JSON_CONTENT_TYPE)


def _is_staff_scope(scope: Scope) -> bool:
    """True when the request carries a Bearer JWT for a tenant staff actor."""
    headers = dict(scope.get("headers", []))
    raw_auth = headers.get(b"authorization", b"").decode("latin-1", errors="ignore")
    if not raw_auth.lower().startswith("bearer "):
        return False
    parts = raw_auth.split(" ", 1)[1].strip().split(".")
    if len(parts) < 2:
        return False
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return False
    email = str(claims.get("email") or "").strip().lower()
    return email.startswith(STAFF_EMAIL_PREFIXES)


def _audit(body: bytes, request_path: str, *, is_staff_caller: bool = False) -> None:
    """Raises `AssertionError` when a JSON response body contains a forbidden key."""
    if not body:
        return
    try:
        payload = json.loads(body)
    except ValueError:
        return
    leaks = forbidden_keys(payload, request_path, is_staff_caller=is_staff_caller)
    if leaks:
        raise AssertionError(
            f"Server-only pricing field(s) in the {request_path} response: {', '.join(leaks[:10])}"
        )
