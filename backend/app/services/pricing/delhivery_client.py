"""
Delhivery B2C (Express) API client: price, pincode serviceability and TAT
(delhivery_api.md §2.1, §3.1, §3.2; DESIGN.md v4 §C.3).

Rules baked in:
- Server-side only, `Authorization: Token <token>` (never Bearer), 3 s timeout.
- The price API allows 50 calls / 5 min per IP for the whole platform: one in-process
  token bucket (45 / 5 min) refuses locally instead of getting the IP blocked.
- Business refusals (HTTP 200/400 with `{"error"}` or `success:false`) raise
  `DelhiveryRefusedError` and are never retried; timeouts / 403 / 429 / 5xx raise
  `DelhiveryUnavailableError` so callers can fall back to the stored price (Q6).
- Pincode and TAT answers are cached in-process for 24 h (they change slowly).

Spring analogy: a `@Component` wrapping `WebClient` with a Resilience4j rate limiter.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, FrozenSet, Mapping, Optional, Protocol, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PRICE_PATH = "/api/kinko/v1/invoice/charges/.json"
PINCODE_PATH = "/c/api/pin-codes/json/"
TAT_PATH = "/api/dc/expected_tat"
REQUEST_TIMEOUT_SECONDS = 3.0
PRICE_CALLS_PER_WINDOW = 45
"""Our own cap, below Delhivery's 50 / 5 min / IP."""
PRICE_WINDOW_SECONDS = 300.0
LOOKUP_CACHE_TTL_SECONDS = 24 * 60 * 60
"""Pincode / TAT answers are reused for 24 h."""
RETRYABLE_STATUS_CODES = frozenset({403, 429, 500, 502, 503, 504})
EMBARGO_REMARK = "embargo"
YES_FLAG = "Y"


class DelhiveryUnavailableError(Exception):
    """Delhivery could not answer now (timeout, throttled, 5xx, auth): use the cache or 'unavailable'."""


class DelhiveryRefusedError(Exception):
    """Delhivery answered with a business refusal (e.g. pincode not serviceable). Never retried."""


class DelhiveryApi(Protocol):
    """The three Delhivery B2C calls the pricing package needs (live client or fake)."""

    async def invoice_charges(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        """`resp[0]` of the price API for the exact query params."""

    async def pincode(self, pincode: str) -> Optional[Dict[str, Any]]:
        """The `postal_code` record, or None when Delhivery does not serve the pin."""

    async def expected_tat(self, origin_pin: str, destination_pin: str, mot: str) -> Optional[int]:
        """Transit days, or None when unknown."""


class _SlidingWindowLimiter:
    """At most `capacity` calls per `window` seconds in this process (refuses, never waits)."""

    def __init__(self, capacity: int, window_seconds: float) -> None:
        self._capacity = capacity
        self._window = window_seconds
        self._calls: Deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Takes one slot or raises DelhiveryUnavailableError when the window is full."""
        async with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] > self._window:
                self._calls.popleft()
            if len(self._calls) >= self._capacity:
                raise DelhiveryUnavailableError("Delhivery price API limit reached; try again shortly.")
            self._calls.append(now)


_PRICE_LIMITER = _SlidingWindowLimiter(PRICE_CALLS_PER_WINDOW, PRICE_WINDOW_SECONDS)
_LOOKUP_CACHE: Dict[Tuple[str, ...], Tuple[float, Any]] = {}


def _cached_lookup(key: Tuple[str, ...]) -> Tuple[bool, Any]:
    """(hit, value) from the 24 h in-process lookup cache."""
    entry = _LOOKUP_CACHE.get(key)
    if entry is None or time.monotonic() - entry[0] > LOOKUP_CACHE_TTL_SECONDS:
        return False, None
    return True, entry[1]


def _store_lookup(key: Tuple[str, ...], value: Any) -> None:
    """Remembers a pincode / TAT answer for 24 h."""
    _LOOKUP_CACHE[key] = (time.monotonic(), value)


class LiveDelhiveryApi:
    """Real HTTP client bound to one Delhivery account token."""

    def __init__(
        self,
        token: str,
        base_url: str,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        """One GET with auth + timeout; maps transport failures to DelhiveryUnavailableError."""
        headers = {"Authorization": f"Token {self._token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.get(f"{self._base_url}{path}", params=dict(params), headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("Delhivery %s failed: %s", path, type(exc).__name__)
            raise DelhiveryUnavailableError("Delhivery did not answer in time.") from exc
        if response.status_code in RETRYABLE_STATUS_CODES or response.status_code == 401:
            logger.warning("Delhivery %s returned HTTP %s", path, response.status_code)
            raise DelhiveryUnavailableError(f"Delhivery returned HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise DelhiveryUnavailableError("Delhivery returned an unreadable answer.") from exc

    async def invoice_charges(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        """Price call (rate limited). Raises DelhiveryRefusedError on `{"error": ...}`."""
        await _PRICE_LIMITER.acquire()
        body = await self._get(PRICE_PATH, params)
        if isinstance(body, dict) and body.get("error"):
            raise DelhiveryRefusedError(str(body["error"]))
        if not isinstance(body, list) or not body or not isinstance(body[0], dict):
            raise DelhiveryUnavailableError("Delhivery returned no price.")
        return body[0]

    async def pincode(self, pincode: str) -> Optional[Dict[str, Any]]:
        """Pincode record (24 h cache). Empty list = not serviceable."""
        hit, cached = _cached_lookup(("pin", pincode))
        if hit:
            return cached
        body = await self._get(PINCODE_PATH, {"filter_codes": pincode})
        codes = body.get("delivery_codes") if isinstance(body, dict) else None
        record = (codes[0] or {}).get("postal_code") if codes else None
        _store_lookup(("pin", pincode), record)
        return record

    async def expected_tat(self, origin_pin: str, destination_pin: str, mot: str) -> Optional[int]:
        """Transit days (24 h cache); business failures return None (not retried)."""
        key = ("tat", origin_pin, destination_pin, mot)
        hit, cached = _cached_lookup(key)
        if hit:
            return cached
        body = await self._get(
            TAT_PATH, {"origin_pin": origin_pin, "destination_pin": destination_pin, "mot": mot, "pdt": "B2C"}
        )
        tat = None
        if isinstance(body, dict) and body.get("success") and isinstance(body.get("data"), dict):
            raw = body["data"].get("tat")
            tat = int(raw) if isinstance(raw, (int, float)) else None
        _store_lookup(key, tat)
        return tat


def is_embargoed(record: Mapping[str, Any]) -> bool:
    """True when the pincode record says 'Embargo' (`remarks`, `remark`, `REMARKS`, or `REMARK`)."""
    remark = str(
        record.get("remarks")
        or record.get("remark")
        or record.get("REMARKS")
        or record.get("REMARK")
        or ""
    )
    return EMBARGO_REMARK in remark.lower()


def flag(record: Mapping[str, Any], name: str) -> bool:
    """A Y/N flag of a pincode record (`pre_paid`, `cod`, `pickup`, `repl`, `is_oda`)."""
    return str(record.get(name) or "").upper() == YES_FLAG


def _slug_set(raw: str) -> FrozenSet[str]:
    """The slugs of a comma-separated `Settings` value (blanks ignored)."""
    return frozenset(slug.strip() for slug in raw.split(",") if slug.strip())


def is_fake_tenant(tenant_slug: str) -> bool:
    """True when `DELHIVERY_FAKE_TENANT_SLUGS` binds the tenant to the fake (set by the test harness only)."""
    return tenant_slug in _slug_set(settings.DELHIVERY_FAKE_TENANT_SLUGS)


def is_live_tenant(tenant_id: str, tenant_slug: str = "") -> bool:
    """
    True when the tenant may use the live Delhivery accounts: its slug is in
    `DELHIVERY_LIVE_TENANT_SLUGS` or its id is `DELHIVERY_TENANT_ID`, and the fake does not
    claim it (the fake wins, so the test harness never spends the live token or rate limit).

    Args:
        tenant_id: The tenant UUID as a string.
        tenant_slug: The tenant slug (empty = match by id only).
    """
    if is_fake_tenant(tenant_slug):
        return False
    bound_id = settings.DELHIVERY_TENANT_ID.strip()
    return (bool(bound_id) and tenant_id == bound_id) or tenant_slug in _slug_set(
        settings.DELHIVERY_LIVE_TENANT_SLUGS
    )


def live_api_if_configured(tenant_id: str, tenant_slug: str = "") -> Optional[LiveDelhiveryApi]:
    """
    The live client for a tenant bound to the Delhivery token, else None.

    Every live client shares this module's price limiter and lookup cache (process-wide).

    Args:
        tenant_id: The tenant UUID as a string.
        tenant_slug: The tenant slug (empty = match by id only).

    Returns:
        A client when `DELHIVERY_B2C_TOKEN` is set and `is_live_tenant` holds.
    """
    if not settings.DELHIVERY_B2C_TOKEN or not is_live_tenant(tenant_id, tenant_slug):
        return None
    return LiveDelhiveryApi(settings.DELHIVERY_B2C_TOKEN, settings.DELHIVERY_B2C_BASE_URL)
