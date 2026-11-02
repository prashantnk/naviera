"""
Runtime configuration of the UI golden layer (ship-readiness plan E3/E4).

Every knob is read from the environment once, so a run can be pointed at a
different Chrome or frontend without code edits. Spring analogy: a
`@ConfigurationProperties("ui-golden")` bean.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Tuple

# --- Environment variable names ---------------------------------------------

CDP_URL_ENV_VAR = "UI_CDP_URL"
FRONTEND_URL_ENV_VAR = "UI_FRONTEND_URL"
SLOW_MO_ENV_VAR = "UI_SLOW_MO_MS"
HIGHLIGHT_ENV_VAR = "UI_HIGHLIGHT_MS"
PASSWORD_ENV_VAR = "GOLDEN_TEST_PASSWORD"

# --- Defaults ----------------------------------------------------------------

DEFAULT_CDP_URL = "http://127.0.0.1:9224"
"""The visible Chrome on the user's Cloudtop (the one `chrome_use` also drives)."""

DEFAULT_FRONTEND_URL = "http://localhost:3000"
DEFAULT_SLOW_MO_MS = 300
DEFAULT_HIGHLIGHT_MS = 450

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

    def url(self, route: str) -> str:
        """
        Builds an absolute tenant URL, e.g. `/login` becomes
        `http://localhost:3000/logismart-test/login` (path-based tenant routing
        handled by the existing `middleware.ts`, which is never modified).
        """
        clean = route if route.startswith("/") else f"/{route}"
        return f"{self.frontend_url.rstrip('/')}/{self.tenant_slug}{clean}"


def load_ui_settings(tenant_slug: str) -> UiSettings:
    """Builds `UiSettings` from the environment for an already-guarded tenant slug."""
    return UiSettings(
        cdp_url=os.getenv(CDP_URL_ENV_VAR, DEFAULT_CDP_URL).strip(),
        frontend_url=os.getenv(FRONTEND_URL_ENV_VAR, DEFAULT_FRONTEND_URL).strip(),
        slow_mo_ms=_int_env(SLOW_MO_ENV_VAR, DEFAULT_SLOW_MO_MS),
        highlight_ms=_int_env(HIGHLIGHT_ENV_VAR, DEFAULT_HIGHLIGHT_MS),
        tenant_slug=tenant_slug,
    )
