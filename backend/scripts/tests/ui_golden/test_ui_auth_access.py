"""
UI check for the lost-membership bug (BUG-auth-403, `llm_resources/.agents/screenshot_bug/REPORT.md`).

A signed-in tab whose `user` row is gone (e.g. a sign-up wiped by the golden reset) must show
`AuthGuard`'s "Access not available + Sign out" screen, never raw backend 403 text in page cards.

1. Fresh load with an orphaned session (canonical test email, JWT `sub` with no `user` row):
   the real backend answers `/users/me` 403 and the guard shows the screen.
2. Mid-session: a tab loaded as customerb2c, then every API call answers 403 (what the
   backend says once the row is deleted). A window focus, and separately any refused API
   call, makes the guard re-check `/users/me` and swap the page for the screen.

Read-only: no database writes; the orphaned session is minted locally. The Sign-out button is
asserted but not clicked (a global Supabase sign-out would revoke the cached role sessions).
"""

import asyncio
import re
import time

import pytest

pytest.importorskip("playwright.async_api")

from golden_journeys.golden_env import CUSTOMER_B2C_EMAIL  # noqa: E402
from playwright.async_api import Page, Response, Route, expect  # noqa: E402

from .auth import write_orphaned_storage_state  # noqa: E402
from .browser_session import UiTab  # noqa: E402
from .pages.base_page import BasePage  # noqa: E402
from .testids import AuthIds  # noqa: E402
from .ui_config import DESKTOP, ELEMENT_TIMEOUT_MS  # noqa: E402
from .ui_fixtures import TabFactory, UiSettings  # noqa: E402

JOURNEY = "AUTH-403"
DASHBOARD_ROUTE = "/dashboard"
API_ROUTE_RE = re.compile(r"/api/v1/")
PROFILE_URL_RE = r"/api/v1/users/me$"
NO_ACCESS_DETAIL = "User does not have access to this tenant."
HTTP_FORBIDDEN = 403
ACCOUNT_MENU_LABEL = "My Account"
"""`aria-label` of the header account button: only rendered inside the authenticated shell."""
DATA_PAGE_LINK = 'a[href$="/delivery-exceptions"]'
"""A sidebar link whose page loads data on mount (client-side navigation, no remount)."""
RECHECK_THROTTLE_SECONDS = 6.0
"""`AuthGuard` re-checks `/users/me` at most every `ACCESS_RECHECK_MIN_INTERVAL_MS` (5 s after
the last check, mount included): a trigger sooner is dropped, so wait past it first."""
POLL_SECONDS = 0.5

EXPECTED_CONSOLE_ERRORS = (
    r"status of 403",  # Chrome logs every refused fetch
    r"Auth check failed",  # AuthGuard's own diagnostic on a refused /users/me
)


def _expect_refusals(tab: UiTab, url_regex: str) -> None:
    """Declares the 403s and their console noise this test provokes on purpose."""
    tab.guard.expect_http(url_regex, HTTP_FORBIDDEN)
    for pattern in EXPECTED_CONSOLE_ERRORS:
        tab.guard.expect_console(pattern)


async def _refuse_all_api_calls(page: Page) -> None:
    """From now on every API call answers like the backend does for a deleted user row."""

    async def _forbid(route: Route) -> None:
        await route.fulfill(status=HTTP_FORBIDDEN, json={"detail": NO_ACCESS_DETAIL})

    await page.route(API_ROUTE_RE, _forbid)


class ProfileCheckClock:
    """Remembers when the page last finished a `/users/me` call (the guard's throttle clock)."""

    def __init__(self, page: Page) -> None:
        self.last_check = time.monotonic()
        page.on("response", self._on_response)

    def _on_response(self, response: Response) -> None:
        if re.search(PROFILE_URL_RE, response.url):
            self.last_check = time.monotonic()

    async def wait_past_throttle(self) -> None:
        """Sleeps until the next trigger is outside the guard's re-check throttle window."""
        while time.monotonic() - self.last_check < RECHECK_THROTTLE_SECONDS:
            await asyncio.sleep(POLL_SECONDS)


async def _open_signed_in_dashboard(page: BasePage) -> None:
    """Opens the dashboard and waits for the authenticated shell (valid membership)."""
    await page.open(DASHBOARD_ROUTE)
    await expect(page.page.get_by_label(ACCOUNT_MENU_LABEL)).to_be_visible(timeout=ELEMENT_TIMEOUT_MS)


async def _expect_access_denied_screen(page: BasePage) -> None:
    """The guard's screen with its Sign-out button replaces the page; no raw 403 text."""
    await expect(page.by_testid(AuthIds.ACCESS_DENIED)).to_be_visible(timeout=ELEMENT_TIMEOUT_MS)
    await expect(page.by_testid(AuthIds.ACCESS_DENIED_SIGN_OUT)).to_be_visible()
    await expect(page.page.get_by_label(ACCOUNT_MENU_LABEL)).to_have_count(0)
    await expect(page.page.get_by_text(NO_ACCESS_DETAIL)).to_have_count(0)


@pytest.mark.ui
async def test_orphaned_session_shows_access_denied_on_load(
    role_tabs: TabFactory, ui_settings: UiSettings, step_banner
) -> None:
    """A session whose user row is gone gets the Sign-out screen from the real backend 403."""
    state = write_orphaned_storage_state(CUSTOMER_B2C_EMAIL, ui_settings)
    tab = await role_tabs.with_storage_state(state, DESKTOP)
    _expect_refusals(tab, PROFILE_URL_RE)
    page = BasePage(tab.page, ui_settings, step_banner)

    await step_banner.show(tab.page, JOURNEY, 1, 1, "Orphaned session opens the dashboard")
    await page.open(DASHBOARD_ROUTE)
    await _expect_access_denied_screen(page)


@pytest.mark.ui
async def test_membership_lost_mid_session_rechecks_and_shows_access_denied(
    role_tabs: TabFactory, ui_settings: UiSettings, step_banner
) -> None:
    """
    After the membership is lost, a focus (outside the throttle window) and a refused API call
    (inside it, so the guard's trailing re-check) each swap in the Sign-out screen.
    """
    tab = await role_tabs.as_role(CUSTOMER_B2C_EMAIL, DESKTOP)
    _expect_refusals(tab, API_ROUTE_RE.pattern)
    page = BasePage(tab.page, ui_settings, step_banner)
    clock = ProfileCheckClock(tab.page)

    await step_banner.show(tab.page, JOURNEY, 1, 2, "Membership lost, user comes back to the tab")
    await _open_signed_in_dashboard(page)
    await clock.wait_past_throttle()  # an immediate re-check (outside the throttle window)
    await _refuse_all_api_calls(tab.page)
    # The guard ignores focus while the tab is hidden; a background CDP tab reports "hidden".
    await tab.page.bring_to_front()
    await tab.page.evaluate("() => window.dispatchEvent(new Event('focus'))")
    await _expect_access_denied_screen(page)

    await step_banner.show(tab.page, JOURNEY, 2, 2, "Membership lost, user opens another page")
    await tab.page.unroute(API_ROUTE_RE)
    await _open_signed_in_dashboard(page)
    await _refuse_all_api_calls(tab.page)  # right after load: inside the window -> trailing re-check
    await page.click_locator(tab.page.locator(DATA_PAGE_LINK).filter(visible=True).first)
    await _expect_access_denied_screen(page)
