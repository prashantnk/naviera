"""
Base page object (ship-readiness plan E3).

A page object wraps one screen: it knows the route and the `data-testid`
selectors, and exposes intent-level methods (`book()`, `confirm_pickup()`).
Journeys never touch raw selectors. Every click and fill flashes the target
first (HUD highlight) so the watching user can follow along.

Spring analogy: a page object is a `@Component` that wraps one screen, like a
Selenium page object with built-in waits.
"""

from decimal import Decimal
from typing import Optional

from playwright.async_api import Locator, Page, expect

from ..hud import StepBanner
from ..money import MoneyLike, assert_screen_money_equals_db, screen_rupees
from ..ui_config import ELEMENT_TIMEOUT_MS, NAVIGATION_TIMEOUT_MS, UiSettings


class BasePage:
    """Shared helpers for every screen."""

    ROUTE: str = "/"
    """Route relative to the tenant root, e.g. `/wallet`. Subclasses override it."""

    def __init__(self, page: Page, settings: UiSettings, banner: StepBanner) -> None:
        """
        Args:
            page: The Playwright page (one browser tab inside a role context).
            settings: Run configuration (frontend URL, tenant slug).
            banner: Shared HUD used for highlights and step labels.
        """
        self.page = page
        self.settings = settings
        self.banner = banner

    # --- Navigation ---------------------------------------------------------

    async def open(self, route: Optional[str] = None) -> "BasePage":
        """Navigates to `route` (default `ROUTE`) under the tenant and waits for the DOM."""
        await self.page.goto(
            self.settings.url(route or self.ROUTE),
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
        return self

    # --- Element access -----------------------------------------------------

    def by_testid(self, test_id: str) -> Locator:
        """Returns the locator for one `data-testid`."""
        return self.page.get_by_test_id(test_id)

    async def click(self, test_id: str) -> None:
        """Highlights then clicks the element with this testid."""
        await self.click_locator(self.by_testid(test_id))

    async def click_locator(self, locator: Locator) -> None:
        """Highlights then clicks any locator (for role/label-based controls)."""
        await locator.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
        await self.banner.highlight(locator)
        await locator.click()

    async def fill(self, test_id: str, value: str) -> None:
        """Highlights then fills the input with this testid."""
        await self.fill_locator(self.by_testid(test_id), value)

    async def fill_locator(self, locator: Locator, value: str) -> None:
        """Highlights then fills any input locator."""
        await locator.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
        await self.banner.highlight(locator)
        await locator.fill(value)

    async def select_option(self, test_id: str, option_label: str) -> None:
        """
        Picks an option in a shadcn/Radix `Select` (button + listbox) by its visible label.

        The trigger carries the testid; the option is found by role inside the
        open listbox portal.
        """
        await self.click(test_id)
        # Exact label first, so "Prepaid" does not also match "Postpaid (... Prepaid ...)".
        exact_span = self.page.get_by_text(option_label, exact=True)
        option = self.page.get_by_role("option").filter(has=exact_span)
        if await option.count() == 0:
            option = self.page.get_by_role("option", name=option_label, exact=False).first
        await self.click_locator(option)

    async def expect_visible(self, test_id: str, timeout: int = ELEMENT_TIMEOUT_MS) -> None:
        """Waits until the element with this testid is visible."""
        await expect(self.by_testid(test_id)).to_be_visible(timeout=timeout)

    def visible_testid(self, test_id: str) -> Locator:
        """
        The visible element with this testid. Responsive pages render the desktop table and
        the mobile cards together and hide one with CSS; only the shown one is on screen.
        """
        return self.by_testid(test_id).filter(visible=True)

    async def text_of(self, test_id: str) -> str:
        """Returns the trimmed visible text of the element."""
        return (await self.visible_testid(test_id).inner_text()).strip()

    # --- Money --------------------------------------------------------------

    async def money(self, test_id: str) -> Decimal:
        """Parses the ₹ amount shown in the element with this testid."""
        return await screen_rupees(self.visible_testid(test_id))

    async def assert_money(self, test_id: str, db_value: MoneyLike, label: str = "") -> Decimal:
        """Asserts the ₹ amount on screen equals `db_value` to the paisa."""
        locator = self.visible_testid(test_id)
        await locator.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
        await self.banner.highlight(locator)
        return await assert_screen_money_equals_db(locator, db_value, label or test_id)
