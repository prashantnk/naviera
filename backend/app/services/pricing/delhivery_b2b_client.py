"""
Delhivery B2B (Cargo / LTL) API client: JWT login, freight estimate, pincode
serviceability and TAT (contract: llm_resources/.agents/pricing/delhivery_b2b_api.md).

Rules baked in:
- Server-side only. `POST /ums/login` (username + password) returns a JWT valid 24 h; one
  token per account is cached in-process for 23 h and refreshed once on HTTP 401.
- A wrong password locks the Delhivery user for 10 minutes and > 100 logins / 5 min block
  the IP, so logins are serialised by a lock and, after a refused login, no new login is
  tried for 10 minutes (the option shows "price unavailable" meanwhile).
- `POST /freight/estimate` allows 100 calls per window: an in-process sliding window (90 /
  5 min) refuses locally. Timeouts: login 5 s, calls 4 s (p99 1.17 s).
- Business refusals (`error` / `message` / `success: false` on HTTP 200/400/404/422) raise
  `DelhiveryRefusedError` (never retried); timeouts / 401 after re-login / 403 / 429 / 5xx and
  "pricing file" errors raise `DelhiveryUnavailableError` so callers fall back to the cache.
- Pincode and TAT answers are cached in-process for 24 h.

Spring analogy: a `@Component` wrapping `WebClient` with a token-refreshing
`ExchangeFilterFunction` and a Resilience4j rate limiter.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

import httpx

from app.core.config import settings
from app.services.pricing.delhivery_client import (
    DelhiveryRefusedError,
    DelhiveryUnavailableError,
    _SlidingWindowLimiter,
    is_live_tenant,
)

logger = logging.getLogger(__name__)

LOGIN_PATH = "/ums/login"
ESTIMATE_PATH = "/freight/estimate"
PINCODE_PATH = "/pincode-service/{pincode}"
TAT_PATH = "/tat/estimate"
LOGIN_TIMEOUT_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 4.0
TOKEN_TTL_SECONDS = 23 * 60 * 60
"""Delhivery JWTs live 24 h; we refresh an hour early."""
LOGIN_BACKOFF_SECONDS = 10 * 60
"""After a refused login, wait out Delhivery's 10-minute user lock before trying again."""
ESTIMATE_CALLS_PER_WINDOW = 90
"""Our own cap, below Delhivery's 100 estimate calls per window."""
ESTIMATE_WINDOW_SECONDS = 300.0
LOOKUP_CACHE_TTL_SECONDS = 24 * 60 * 60
UNAVAILABLE_STATUS_CODES = frozenset({403, 429, 500, 502, 503, 504})
REFUSAL_STATUS_CODES = frozenset({400, 404, 422})
UNAUTHORIZED_STATUS = 401
PRICING_FILE_MARKER = "pricing file"
"""'Pricing File Not exist': the account has no rate card — a setup gap, not a route refusal."""
NOT_SERVICEABLE_MARKERS = ("not serviceable", "invalid pincode", "not valid pin", "not found in database")
ERROR_KEYS = ("error", "errors", "message", "detail", "msg")
SERVICEABLE_FLAG_KEYS = ("serviceable", "is_serviceable")
COD_FLAG_KEYS = ("cod", "is_cod", "cod_serviceable", "cod_available")
NEGATIVE_STRING_FLAGS = frozenset({"N", "NO", "FALSE", "0"})
TAT_KEYS = ("tat", "tat_days", "expected_tat", "days")


class DelhiveryB2BApi(Protocol):
    """The three Delhivery B2B calls the pricing package needs (live client or fake)."""

    async def estimate(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """The raw JSON answer of `POST /freight/estimate` for the exact body."""

    async def pincode_serviceable(
        self, pincode: str, weight_g: int, *, is_cod: bool = False, is_origin: bool = False
    ) -> bool:
        """False when Delhivery B2B does not serve the pin (or does not support pickup / COD)."""

    async def tat_days(self, origin_pin: str, destination_pin: str) -> Optional[int]:
        """Transit days, or None when unknown."""


@dataclass
class _TokenState:
    """The cached JWT of one Delhivery B2B account and the login back-off."""

    token: Optional[str] = None
    expires_at: float = 0.0
    login_blocked_until: float = 0.0


_ESTIMATE_LIMITER = _SlidingWindowLimiter(ESTIMATE_CALLS_PER_WINDOW, ESTIMATE_WINDOW_SECONDS)
_TOKENS: Dict[Tuple[str, str], _TokenState] = {}
_TOKEN_LOCK = asyncio.Lock()
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


def reset_state() -> None:
    """Forgets cached tokens, back-offs, lookups and limiter slots (tests, credential rotation)."""
    _TOKENS.clear()
    _LOOKUP_CACHE.clear()
    _ESTIMATE_LIMITER._calls.clear()


def error_text(body: Any) -> Optional[str]:
    """
    The business error message of a Delhivery B2B answer, if any.

    Args:
        body: Parsed JSON (dict, list or scalar).

    Returns:
        The first error-like message, or None for a success-shaped answer.
    """
    if not isinstance(body, dict):
        return None
    for key in ERROR_KEYS:
        value = body.get(key)
        if value:
            return str(value)
    if body.get("success") is False:
        return str(body.get("data") or "Delhivery refused the request.")
    return None


def _jwt_from(body: Any) -> Optional[str]:
    """The JWT of a login answer (`data.jwt`, tolerating `jwt` / `token` at either level)."""
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    for container in (data if isinstance(data, dict) else {}, body):
        for key in ("jwt", "token", "access_token"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _first_int(container: Any, keys: Tuple[str, ...]) -> Optional[int]:
    """The first integer-like value under `keys` in a dict (or the first dict of a list)."""
    if isinstance(container, list):
        container = next((item for item in container if isinstance(item, dict)), None)
    if not isinstance(container, dict):
        return None
    for key in keys:
        value = container.get(key)
        try:
            if value is not None and not isinstance(value, bool):
                return int(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            continue
    return None


def _is_not_serviceable(message: str) -> bool:
    """True when an error message says the pincode is outside Delhivery's network."""
    lowered = message.lower()
    return any(marker in lowered for marker in NOT_SERVICEABLE_MARKERS)


class LiveDelhiveryB2BApi:
    """Real HTTP client bound to one Delhivery B2B account (username + password)."""

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._state_key = (self._base_url, username)

    # --- auth -----------------------------------------------------------------------

    def _state(self) -> _TokenState:
        """The shared token state of this account."""
        return _TOKENS.setdefault(self._state_key, _TokenState())

    async def _token(self, *, force_refresh: bool = False) -> str:
        """
        A valid JWT: the cached one, else one login (serialised; 10-min back-off after refusal).

        Raises:
            DelhiveryUnavailableError: login refused, backed off, or Delhivery unreachable.
        """
        async with _TOKEN_LOCK:
            state = self._state()
            now = time.monotonic()
            if not force_refresh and state.token and now < state.expires_at:
                return state.token
            if now < state.login_blocked_until:
                raise DelhiveryUnavailableError("Delhivery B2B login is paused after a refused login.")
            token = await self._login(state)
            state.token, state.expires_at = token, time.monotonic() + TOKEN_TTL_SECONDS
            return token

    async def _login(self, state: _TokenState) -> str:
        """One `POST /ums/login`; a refusal arms the back-off."""
        try:
            async with httpx.AsyncClient(timeout=LOGIN_TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(
                    f"{self._base_url}{LOGIN_PATH}",
                    json={"username": self._username, "password": self._password},
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.warning("Delhivery B2B login failed: %s", type(exc).__name__)
            raise DelhiveryUnavailableError("Delhivery B2B login did not answer in time.") from exc
        token = _jwt_from(self._json_or_none(response)) if response.status_code == 200 else None
        if token is None:
            state.token = None
            if response.status_code not in UNAVAILABLE_STATUS_CODES:
                state.login_blocked_until = time.monotonic() + LOGIN_BACKOFF_SECONDS
            logger.error("Delhivery B2B login refused (HTTP %s); check DELHIVERY_B2B_* settings.", response.status_code)
            raise DelhiveryUnavailableError(f"Delhivery B2B login refused (HTTP {response.status_code}).")
        return token

    # --- transport --------------------------------------------------------------------

    @staticmethod
    def _json_or_none(response: httpx.Response) -> Any:
        """The JSON body, or None when it is not JSON."""
        try:
            return response.json()
        except ValueError:
            return None

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One authorised request; on 401 logs in again once and retries."""
        for attempt in range(2):
            token = await self._token(force_refresh=attempt > 0)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, transport=self._transport) as client:
                    response = await client.request(method, f"{self._base_url}{path}", headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                logger.warning("Delhivery B2B %s failed: %s", path, type(exc).__name__)
                raise DelhiveryUnavailableError("Delhivery B2B did not answer in time.") from exc
            if response.status_code != UNAUTHORIZED_STATUS:
                return response
            self._state().token = None
        raise DelhiveryUnavailableError("Delhivery B2B rejected the login token.")

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        """A request mapped to (JSON body | DelhiveryRefusedError | DelhiveryUnavailableError)."""
        response = await self._send(method, path, **kwargs)
        body = self._json_or_none(response)
        if response.status_code in UNAVAILABLE_STATUS_CODES:
            logger.warning("Delhivery B2B %s returned HTTP %s", path, response.status_code)
            raise DelhiveryUnavailableError(f"Delhivery B2B returned HTTP {response.status_code}.")
        message = error_text(body)
        if response.status_code in REFUSAL_STATUS_CODES or message:
            detail = message or f"HTTP {response.status_code}"
            if PRICING_FILE_MARKER in detail.lower():
                raise DelhiveryUnavailableError(f"Delhivery B2B has no rate card for this account: {detail}")
            raise DelhiveryRefusedError(detail)
        if body is None or response.status_code >= 300:
            raise DelhiveryUnavailableError("Delhivery B2B returned an unreadable answer.")
        return body

    # --- API ------------------------------------------------------------------------------

    async def estimate(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """`POST /freight/estimate` (rate limited). Returns the raw JSON object."""
        await _ESTIMATE_LIMITER.acquire()
        answer = await self._call("POST", ESTIMATE_PATH, json=dict(body))
        if not isinstance(answer, dict):
            raise DelhiveryUnavailableError("Delhivery B2B returned no estimate.")
        return answer

    async def pincode_serviceable(
        self, pincode: str, weight_g: int, *, is_cod: bool = False, is_origin: bool = False
    ) -> bool:
        """`GET /pincode-service/{pin}` (24 h cache). A 'not serviceable' refusal → False."""
        check_cod = bool(is_cod and not is_origin)
        mode_key = ("pin", pincode, "cod" if check_cod else "std")
        hit, cached = _cached_lookup(mode_key)
        if hit:
            return bool(cached)
        raw_hit, body = _cached_lookup(("pin_raw", pincode))
        if not raw_hit:
            try:
                body = await self._call("GET", PINCODE_PATH.format(pincode=pincode), params={"weight": weight_g})
            except DelhiveryRefusedError as exc:
                if not _is_not_serviceable(str(exc)):
                    raise
                body = {"serviceable": False}
            _store_lookup(("pin_raw", pincode), body)
        serviceable = self._serviceable_flag(body, is_cod=check_cod)
        _store_lookup(mode_key, serviceable)
        return serviceable

    @staticmethod
    def _serviceable_flag(body: Any, *, is_cod: bool = False) -> bool:
        """An explicit `serviceable: false` (or `cod: false`/`'N'` when `is_cod=True`) → False; else True."""
        data = body.get("data") if isinstance(body, dict) else None
        for container in (body, data):
            if isinstance(container, dict):
                for key in SERVICEABLE_FLAG_KEYS:
                    if container.get(key) is False:
                        return False
                if is_cod:
                    for key in COD_FLAG_KEYS:
                        val = container.get(key)
                        if val is False or (isinstance(val, str) and val.strip().upper() in NEGATIVE_STRING_FLAGS):
                            return False
        return True

    async def tat_days(self, origin_pin: str, destination_pin: str) -> Optional[int]:
        """`GET /tat/estimate` (24 h cache); refusals and unknown shapes → None."""
        key = ("tat", origin_pin, destination_pin)
        hit, cached = _cached_lookup(key)
        if hit:
            return cached
        try:
            body = await self._call("GET", TAT_PATH, params={"origin_pin": origin_pin, "destination_pin": destination_pin})
        except DelhiveryRefusedError:
            body = None
        data = body.get("data", body) if isinstance(body, dict) else None
        tat = _first_int(data, TAT_KEYS)
        _store_lookup(key, tat)
        return tat


def b2b_credentials_configured() -> bool:
    """True when the Delhivery B2B username and password are both set."""
    return bool(settings.DELHIVERY_B2B_USERNAME.strip() and settings.DELHIVERY_B2B_PASSWORD)


def live_b2b_api_if_configured(tenant_id: str, tenant_slug: str = "") -> Optional[LiveDelhiveryB2BApi]:
    """
    The live B2B client for a tenant bound to the Delhivery account, else None.

    Every live client shares this module's JWT cache, estimate limiter and lookup cache
    (process-wide, keyed by account, never by tenant).

    Args:
        tenant_id: The tenant UUID as a string.
        tenant_slug: The tenant slug (empty = match by id only).

    Returns:
        A client when `DELHIVERY_B2B_USERNAME/PASSWORD` are set and `is_live_tenant` holds.
    """
    if not b2b_credentials_configured() or not is_live_tenant(tenant_id, tenant_slug):
        return None
    return LiveDelhiveryB2BApi(
        settings.DELHIVERY_B2B_USERNAME.strip(), settings.DELHIVERY_B2B_PASSWORD, settings.DELHIVERY_B2B_BASE_URL
    )
