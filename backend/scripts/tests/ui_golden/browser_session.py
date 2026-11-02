"""
Attaches to the visible Chrome over CDP and opens isolated contexts (plan E4).

Two modes:
- **Attached (default):** the shared Chrome on the Cloudtop runs with
  `--remote-debugging-port=9224`. We never close that browser: each test opens its
  own incognito-like `BrowserContext` (separate cookies/localStorage per role) and
  closes only the contexts it created.
- **Self-launched:** when nothing answers on the CDP URL (or `UI_HEADLESS=1`), the
  harness launches its own headless Chrome (`UI_CHROME_PATH`, else
  `/opt/google/chrome/chrome` when present, else the first `google-chrome` /
  `chromium` / `chromium-browser` on `PATH`) with a throw-away profile and closes
  only that one.
"""

from dataclasses import dataclass, field
import os
import shutil
from typing import List, Optional, Sequence

import httpx
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .network_guard import NetworkGuard
from .ui_config import (
    DEFAULT_TIMEOUT_MS,
    NAVIGATION_TIMEOUT_MS,
    PHONE,
    VIEWPORTS,
    UiSettings,
)

PHONE_DEVICE_SCALE_FACTOR = 3
INDIA_LOCALE = "en-IN"
INDIA_TIMEZONE = "Asia/Kolkata"
CDP_CONNECT_TIMEOUT_MS = 15_000
CDP_HTTP_TIMEOUT_S = 2.0
CHROME_PATH_ENV_VAR = "UI_CHROME_PATH"
CHROME_BINARY_NAMES = ("google-chrome", "chromium", "chromium-browser")
DEFAULT_CHROME_PATH = "/opt/google/chrome/chrome"
HEADLESS_CHROME_ARGS = ("--no-proxy-server",)


def resolve_chrome_path() -> str:
    """
    Chrome binary for the self-launched mode.

    Returns:
        `UI_CHROME_PATH` when set; else `DEFAULT_CHROME_PATH` when that binary exists
        (Google Chrome's real binary, not the `/usr/bin/google-chrome` shell wrapper);
        else the first of `CHROME_BINARY_NAMES` found on `PATH` (e.g. Chromium in a
        Codespace); else `DEFAULT_CHROME_PATH`, so Playwright's error names a path.
    """
    configured = os.getenv(CHROME_PATH_ENV_VAR)
    if configured:
        return configured
    if os.path.isfile(DEFAULT_CHROME_PATH):
        return DEFAULT_CHROME_PATH
    for name in CHROME_BINARY_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return DEFAULT_CHROME_PATH


class CdpUnavailableError(RuntimeError):
    """Raised when no Chrome answers on the configured CDP URL."""


@dataclass
class UiTab:
    """One page plus the guard watching it."""

    context: BrowserContext
    page: Page
    guard: NetworkGuard
    viewport: str


@dataclass
class CdpSession:
    """The Playwright driver + CDP connection + every context this run created."""

    playwright: Playwright
    browser: Browser
    settings: UiSettings
    app_origins: Sequence[str]
    owns_browser: bool = False
    _owned: List[BrowserContext] = field(default_factory=list)

    async def new_tab(self, viewport: str, storage_state: Optional[str] = None) -> UiTab:
        """
        Opens a fresh context (optionally pre-authenticated) and one page in it.

        Args:
            viewport: `desktop` (1440x900) or `phone` (390x844, touch, mobile UA flags).
            storage_state: Path to a cached Playwright storage-state JSON, or None.
        """
        width, height = VIEWPORTS[viewport]
        is_phone = viewport == PHONE
        context = await self.browser.new_context(
            viewport={"width": width, "height": height},
            is_mobile=is_phone,
            has_touch=is_phone,
            device_scale_factor=PHONE_DEVICE_SCALE_FACTOR if is_phone else 1,
            locale=INDIA_LOCALE,
            timezone_id=INDIA_TIMEZONE,
            storage_state=storage_state,
            accept_downloads=True,
        )
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        self._owned.append(context)
        page = await context.new_page()
        guard = NetworkGuard(app_origins=self.app_origins).attach(page)
        await page.bring_to_front()
        return UiTab(context=context, page=page, guard=guard, viewport=viewport)

    async def close_owned(self) -> None:
        """Closes only the contexts this run created; the user's windows stay open."""
        while self._owned:
            context = self._owned.pop()
            try:
                await context.close()
            except Exception:  # noqa: BLE001 - already closed by the test is fine
                pass

    async def disconnect(self) -> None:
        """
        Closes owned contexts and stops the driver. A shared CDP Chrome keeps running;
        only a browser this run launched itself (`owns_browser`) is closed.
        """
        await self.close_owned()
        if self.owns_browser:
            await self.browser.close()
        await self.playwright.stop()


async def _heal_stuck_cdp_pages(cdp_url: str) -> None:
    """
    Replaces any uncommitted startup tab (`title == ''` and non-blank URL).

    When Chrome is launched with an initial URL before the frontend server is
    ready, that first tab stays in an uncommitted navigation state and causes
    Playwright's `connect_over_cdp` to wait indefinitely on `Page.enable`.
    """
    base = cdp_url.rstrip("/")
    async with httpx.AsyncClient(timeout=CDP_HTTP_TIMEOUT_S) as client:
        resp = await client.get(f"{base}/json")
        resp.raise_for_status()
        targets = resp.json()
        pages = [t for t in targets if t.get("type") == "page"]
        stuck = [
            t
            for t in pages
            if not t.get("title") and not str(t.get("url", "")).startswith("about:")
        ]
        if not stuck:
            return
        if len(stuck) == len(pages):
            await client.put(f"{base}/json/new?about:blank")
        for target in stuck:
            target_id = target.get("id")
            if target_id:
                await client.get(f"{base}/json/close/{target_id}")


async def connect_cdp(settings: UiSettings, app_origins: Sequence[str]) -> CdpSession:
    """
    Connects to the visible Chrome with `slow_mo` so every action is watchable.

    Raises:
        CdpUnavailableError: When nothing listens on `settings.cdp_url`.
    """
    try:
        await _heal_stuck_cdp_pages(settings.cdp_url)
    except Exception as exc:
        raise CdpUnavailableError(
            f"No Chrome answers on {settings.cdp_url}. Start the visible Chrome with "
            f"--remote-debugging-port, or set UI_CDP_URL. ({exc})"
        ) from exc
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(
            settings.cdp_url,
            slow_mo=settings.slow_mo_ms,
            timeout=CDP_CONNECT_TIMEOUT_MS,
        )
    except Exception as exc:
        await playwright.stop()
        raise CdpUnavailableError(
            f"No Chrome answers on {settings.cdp_url}. Start the visible Chrome with "
            f"--remote-debugging-port, or set UI_CDP_URL. ({exc})"
        ) from exc
    return CdpSession(
        playwright=playwright, browser=browser, settings=settings, app_origins=app_origins
    )


async def launch_headless(settings: UiSettings, app_origins: Sequence[str]) -> CdpSession:
    """
    Launches a private headless Chrome (fresh temp profile) owned by this run.

    Used when the shared CDP Chrome is unreachable or `UI_HEADLESS=1`; `disconnect()`
    closes it again.
    """
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(
            executable_path=resolve_chrome_path(),
            headless=True,
            slow_mo=settings.slow_mo_ms,
            args=list(HEADLESS_CHROME_ARGS),
        )
    except Exception:
        await playwright.stop()
        raise
    return CdpSession(
        playwright=playwright,
        browser=browser,
        settings=settings,
        app_origins=app_origins,
        owns_browser=True,
    )
