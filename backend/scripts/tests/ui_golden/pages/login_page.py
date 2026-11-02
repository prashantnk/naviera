"""Login page (`/<tenant>/login`): password sign-in for role sessions."""

import re

from playwright.async_api import expect

from ..testids import LoginIds
from ..ui_config import NAVIGATION_TIMEOUT_MS
from .base_page import BasePage

SIGN_IN_BUTTON_NAME = "Sign In"
LOGIN_PATH_RE = re.compile(r"/login(?:[/?#]|$)")


class LoginPage(BasePage):
    """The tenant-branded login screen."""

    ROUTE = "/login"

    async def open_root_login(self) -> None:
        """Opens `/login` (platform login route; works before the test tenant is seeded)."""
        await self.page.goto(f"{self.settings.frontend_url}{self.ROUTE}", wait_until="load")

    async def expect_loaded(self) -> None:
        """Waits until the Sign In tab is rendered (the page hydrated)."""
        await expect(self.by_testid(LoginIds.TAB_SIGNIN)).to_be_visible(
            timeout=NAVIGATION_TIMEOUT_MS
        )

    async def sign_in_with_password(self, email: str, password: str) -> None:
        """
        Signs in through the real Supabase password flow and waits to leave `/login`.

        The password is never logged; only the email is shown in the HUD.
        """
        await self.expect_loaded()
        await self.click(LoginIds.TAB_SIGNIN)
        await self.fill_locator(self.page.locator(f"#{LoginIds.EMAIL_INPUT_ID}"), email)
        await self.fill_locator(self.page.locator(f"#{LoginIds.PASSWORD_INPUT_ID}"), password)
        submit = self.page.get_by_role("button", name=SIGN_IN_BUTTON_NAME, exact=True)
        await self.click_locator(submit)
        await self.page.wait_for_url(
            lambda url: not LOGIN_PATH_RE.search(url), timeout=NAVIGATION_TIMEOUT_MS
        )
