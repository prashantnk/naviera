"""
Fixtures of the UI click-through golden layer (ship-readiness plan E3/E4).

Imported by `conftest.py` only when Playwright is installed (dev group `e2e`).

What it provides:
- `cdp_session` (session): attaches to the visible Chrome on `UI_CDP_URL`
  (default `http://127.0.0.1:9224`) with `slow_mo` (default 300 ms) and closes only
  the contexts it opens. If that Chrome is unreachable (or `UI_HEADLESS=1`), it
  launches a private headless Chrome instead and closes only that browser.
- `step_banner`: the on-page HUD ("J09 step 3/7: Book shipment") + highlight-before-click.
- `ui_tabs`: factory for anonymous tabs (`await ui_tabs.anonymous("phone")`).
  Every tab carries a `NetworkGuard`; unexpected 4xx/5xx or console errors fail
  the test at teardown.
- `role_tabs`: factory for logged-in tabs (`await role_tabs.as_role(CUSTOMER_B2C_EMAIL)`),
  login once per account with a cached `storage_state`. Needs the seeded
  `logismart-test` tenant and `GOLDEN_TEST_PASSWORD`.
- `ui_tenant` / `db_oracle`: the guarded test tenant and its read-only oracle.

Spring analogy: a JUnit 5 extension that owns one shared WebDriver, plus
per-test `@BeforeEach` page setup and an `@AfterEach` "no errors" assertion.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, List, Optional

import pytest

# `golden_env` refuses a non-test slug at import time (before any browser opens).
from golden_journeys.golden_env import (
    GOLDEN_TENANT_SLUG,
    acquire_run_lock,
    load_test_tenant,
    release_run_lock,
)

from .auth import ensure_storage_state
from .browser_session import (
    CdpSession,
    CdpUnavailableError,
    UiTab,
    connect_cdp,
    launch_headless,
)
from .db_oracle import DbOracle
from .hud import StepBanner
from .ui_config import (
    API_URL_ENV_VAR,
    DEFAULT_API_URL,
    DESKTOP,
    UiSettings,
    load_ui_settings,
)

HEADLESS_ENV_VAR = "UI_HEADLESS"


def api_url() -> str:
    """Backend base URL (requests may go to it directly as well as through Next.js)."""
    return os.getenv(API_URL_ENV_VAR, DEFAULT_API_URL).strip()


# --- Browser ----------------------------------------------------------------


@pytest.fixture(scope="session")
def ui_settings() -> UiSettings:
    """Run configuration bound to the guarded golden tenant slug."""
    return load_ui_settings(GOLDEN_TENANT_SLUG)


@pytest.fixture(scope="session")
async def cdp_session(ui_settings: UiSettings) -> AsyncIterator[CdpSession]:
    """
    One browser session for the whole run: the shared CDP Chrome when it answers,
    otherwise (or with `UI_HEADLESS=1`) a private headless Chrome this run owns.
    """
    origins = (ui_settings.frontend_url, api_url())
    session: Optional[CdpSession] = None
    if os.getenv(HEADLESS_ENV_VAR) != "1":
        try:
            session = await connect_cdp(ui_settings, app_origins=origins)
        except CdpUnavailableError:
            session = None
    if session is None:
        session = await launch_headless(ui_settings, app_origins=origins)
    try:
        yield session
    finally:
        await session.disconnect()


@pytest.fixture
def step_banner(ui_settings: UiSettings) -> StepBanner:
    """Fresh HUD per test (banner text + highlight duration)."""
    return StepBanner(highlight_ms=ui_settings.highlight_ms)


@dataclass
class TabFactory:
    """Opens tabs for one test and checks every guard when the test ends."""

    session: CdpSession
    banner: StepBanner
    tabs: List[UiTab] = field(default_factory=list)

    async def anonymous(self, viewport: str = DESKTOP) -> UiTab:
        """A logged-out tab (no storage state)."""
        tab = await self.session.new_tab(viewport)
        self.tabs.append(tab)
        return tab

    async def as_role(self, email: str, viewport: str = DESKTOP) -> UiTab:
        """A tab logged in as one canonical test account (login once, then cached)."""
        state = await ensure_storage_state(self.session, self.banner, email)
        tab = await self.session.new_tab(viewport, storage_state=str(state))
        self.tabs.append(tab)
        return tab

    async def with_storage_state(self, state: Path, viewport: str = DESKTOP) -> UiTab:
        """A tab opened with a prepared storage state (e.g. an orphaned session)."""
        tab = await self.session.new_tab(viewport, storage_state=str(state))
        self.tabs.append(tab)
        return tab

    async def close(self) -> Optional[str]:
        """Closes this test's tabs and returns the combined guard report (None if clean)."""
        reports = []
        for tab in self.tabs:
            try:
                tab.guard.assert_clean()
            except AssertionError as exc:
                reports.append(f"[{tab.viewport}] {exc}")
            try:
                await tab.context.close()
            except Exception:  # noqa: BLE001 - already closed by the test
                pass
        self.tabs.clear()
        return "\n".join(reports) or None


@pytest.fixture
async def ui_tabs(cdp_session: CdpSession, step_banner: StepBanner) -> AsyncIterator[TabFactory]:
    """Anonymous-tab factory; fails the test at teardown on unexpected browser errors."""
    factory = TabFactory(cdp_session, step_banner)
    yield factory
    report = await factory.close()
    if report:
        pytest.fail(report)


# --- Tenant, logged-in tabs, oracle -----------------------------------------


@pytest.fixture(scope="session")
async def ui_tenant() -> AsyncIterator[object]:
    """
    The guarded `logismart-test` tenant, with the golden run lock held.

    It does NOT reset the tenant: the one-command run (plan E7) resets once
    before the API suites, and the UI suites build on that state.
    """
    tenant = await load_test_tenant(GOLDEN_TENANT_SLUG)
    handle = acquire_run_lock()
    try:
        yield tenant
    finally:
        release_run_lock(handle)


@pytest.fixture
async def role_tabs(
    ui_tenant: object, cdp_session: CdpSession, step_banner: StepBanner
) -> AsyncIterator[TabFactory]:
    """Logged-in tab factory (requires the seeded test tenant)."""
    factory = TabFactory(cdp_session, step_banner)
    yield factory
    report = await factory.close()
    if report:
        pytest.fail(report)


@pytest.fixture(scope="session")
def db_oracle(ui_tenant: object) -> DbOracle:
    """Read-only oracle bound to the test tenant id."""
    return DbOracle(tenant_id=getattr(ui_tenant, "id"))
