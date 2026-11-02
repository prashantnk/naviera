"""
UI smoke test (ship-readiness plan E4): proves the harness drives the visible
Chrome. It opens the tenant login page in a fresh anonymous context, shows the
step banner, re-checks it after a reload, flashes the Sign In tab, and asserts
no unexpected browser errors. No login, no DB access, no writes.
"""

import httpx
import pytest

pytest.importorskip(
    "playwright.async_api",
    reason="UI layer needs the `e2e` dev group (pytest-playwright); run `poetry install --with e2e`.",
)

from .hud import HUD_TEST_ID, read_banner  # noqa: E402
from .pages.login_page import LoginPage  # noqa: E402
from .testids import LoginIds  # noqa: E402
from .ui_fixtures import TabFactory, api_url  # noqa: E402
from .ui_config import DESKTOP, UiSettings  # noqa: E402

JOURNEY = "SMOKE"
TOTAL_STEPS = 3
TENANT_CONFIG_PATH = "/api/v1/tenants/config"
HTTP_NOT_FOUND = 404
PROBE_TIMEOUT_SECONDS = 10.0


async def _tenant_config_status(slug: str) -> int:
    """Read-only HTTP probe: is the test tenant seeded yet (200) or not (404)?"""
    async with httpx.AsyncClient(base_url=api_url(), timeout=PROBE_TIMEOUT_SECONDS) as client:
        resp = await client.get(TENANT_CONFIG_PATH, headers={"X-Tenant-Slug": slug})
    return resp.status_code


async def test_login_page_banner_and_highlight(
    ui_tabs: TabFactory, ui_settings: UiSettings, step_banner
) -> None:
    """Login page renders, the banner shows/survives a reload, and the page is error-free."""
    tab = await ui_tabs.anonymous(DESKTOP)
    login = LoginPage(tab.page, ui_settings, step_banner)
    if await _tenant_config_status(ui_settings.tenant_slug) == HTTP_NOT_FOUND:
        # Before `logismart-test` is seeded, `/logismart-test/login` returns Next.js 404;
        # open `/login` (platform login page) so the smoke test still exercises the real form.
        await login.open_root_login()
    else:
        await login.open()
    await login.expect_loaded()

    label_1 = await step_banner.show(tab.page, JOURNEY, 1, TOTAL_STEPS, "Open login page")
    assert label_1 == "SMOKE step 1/3: Open login page"
    assert await tab.page.get_by_test_id(HUD_TEST_ID).inner_text() == label_1

    await step_banner.show(tab.page, JOURNEY, 2, TOTAL_STEPS, "Highlight Sign In tab")
    await step_banner.highlight(login.by_testid(LoginIds.TAB_SIGNIN))

    label_3 = await step_banner.show(tab.page, JOURNEY, 3, TOTAL_STEPS, "Banner survives reload")
    await tab.page.reload(wait_until="load")
    await login.expect_loaded()
    await tab.page.wait_for_function(
        "([id, text]) => document.querySelector(`[data-testid='${id}']`)?.textContent === text",
        arg=[HUD_TEST_ID, label_3],
    )
    assert await read_banner(tab.page) == label_3
    tab.guard.assert_clean()
