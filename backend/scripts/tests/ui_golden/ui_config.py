"""
Runtime configuration of the UI golden layer (ship-readiness plan E3/E4).

Every knob is read from the environment once, so a run can be pointed at a
different Chrome or frontend without code edits. Spring analogy: a
`@ConfigurationProperties("ui-golden")` bean.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple
from urllib.parse import urlsplit, urlunsplit

# --- Environment variable names ---------------------------------------------

CDP_URL_ENV_VAR = "UI_CDP_URL"
FRONTEND_URL_ENV_VAR = "UI_FRONTEND_URL"
API_URL_ENV_VAR = "UI_API_URL"
SLOW_MO_ENV_VAR = "UI_SLOW_MO_MS"
HIGHLIGHT_ENV_VAR = "UI_HIGHLIGHT_MS"
PASSWORD_ENV_VAR = "GOLDEN_TEST_PASSWORD"

# --- Defaults ----------------------------------------------------------------

DEFAULT_CDP_URL = "http://127.0.0.1:9224"
"""The visible Chrome on the user's Cloudtop (the one `chrome_use` also drives)."""

DEFAULT_FRONTEND_URL = "http://localhost:3000"
DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_SLOW_MO_MS = 300
DEFAULT_HIGHLIGHT_MS = 450

BACKEND_PROXY_ROUTE_RE = re.compile(r"^https?://[^/]+(?:/api/v1(?:/|$|\?)|/health(?:$|\?))")
"""Browser paths that Next.js proxies to FastAPI (`/api/v1/*` and `/health`, not `/api/revalidate`)."""

DEFAULT_TIMEOUT_MS = 15_000
NAVIGATION_TIMEOUT_MS = 45_000
ELEMENT_TIMEOUT_MS = 60_000
"""Data-backed elements: first paint waits on API calls over the slow shared DB pooler."""
MONEY_WRITE_TIMEOUT_MS = 120_000
"""Dialogs that submit a money write (re-price + GST note + wallet); = Next `proxyTimeout`."""
"""Next.js dev compiles a route on first hit, which can take tens of seconds."""

DESKTOP_VIEWPORT: Tuple[int, int] = (1440, 900)
PHONE_VIEWPORT: Tuple[int, int] = (390, 844)
DESKTOP = "desktop"
PHONE = "phone"
VIEWPORTS = {DESKTOP: DESKTOP_VIEWPORT, PHONE: PHONE_VIEWPORT}

STORAGE_STATE_DIR = Path("/tmp")
STORAGE_STATE_PREFIX = "naviera_ui_golden"
ARTIFACT_DIR = Path("/tmp") / "naviera_ui_golden_artifacts"


def _int_env(name: str, default: int) -> int:
    """Reads a non-negative integer environment variable, falling back to `default`."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


@dataclass(frozen=True)
class UiSettings:
    """Immutable snapshot of the UI run configuration."""

    cdp_url: str
    frontend_url: str
    slow_mo_ms: int
    highlight_ms: int
    tenant_slug: str
    api_url: str = DEFAULT_API_URL

    def url(self, route: str) -> str:
        """
        Builds an absolute tenant URL, e.g. `/login` becomes
        `http://localhost:3000/logismart-test/login` (path-based tenant routing
        handled by the existing `middleware.ts`, which is never modified).
        """
        clean = route if route.startswith("/") else f"/{route}"
        return f"{self.frontend_url.rstrip('/')}/{self.tenant_slug}{clean}"


def rewrite_api_url(request_url: str, target_api_url: str) -> str:
    """
    Replaces the scheme + host:port of `request_url` with `target_api_url`, keeping the
    path and query string intact so browser `/api/v1/*` calls go to the UI phase's own
    fake-env uvicorn instead of the shared `:8000` backend behind Next.js `:3000`.
    """
    parsed_req = urlsplit(request_url)
    parsed_api = urlsplit(target_api_url.rstrip("/"))
    if not parsed_api.scheme or not parsed_api.netloc:
        return request_url
    base_path = parsed_api.path.rstrip("/")
    return urlunsplit(
        (
            parsed_api.scheme,
            parsed_api.netloc,
            f"{base_path}{parsed_req.path}",
            parsed_req.query,
            parsed_req.fragment,
        )
    )


def load_ui_settings(tenant_slug: str) -> UiSettings:
    """Builds `UiSettings` from the environment for an already-guarded tenant slug."""
    return UiSettings(
        cdp_url=os.getenv(CDP_URL_ENV_VAR, DEFAULT_CDP_URL).strip(),
        frontend_url=os.getenv(FRONTEND_URL_ENV_VAR, DEFAULT_FRONTEND_URL).strip(),
        slow_mo_ms=_int_env(SLOW_MO_ENV_VAR, DEFAULT_SLOW_MO_MS),
        highlight_ms=_int_env(HIGHLIGHT_ENV_VAR, DEFAULT_HIGHLIGHT_MS),
        tenant_slug=tenant_slug,
        api_url=os.getenv(API_URL_ENV_VAR, DEFAULT_API_URL).strip(),
    )
