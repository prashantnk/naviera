"""
Mobile `/ops` field-executive view, used at 390x844 (plan B5, E4 phone viewport).

The rider opens a My Pickups card, types the actual pieces per LR and confirms.
"""

from typing import Mapping

from ..testids import OpsIds
from ..ui_config import ELEMENT_TIMEOUT_MS, MONEY_WRITE_TIMEOUT_MS, PHONE_VIEWPORT
from .base_page import BasePage


class OpsMobilePage(BasePage):
    """Rider workspace."""

    ROUTE = "/ops"

    async def assert_phone_viewport(self) -> None:
        """Fails when the page is not rendered at the 390x844 phone size."""
        size = self.page.viewport_size or {}
        actual = (size.get("width"), size.get("height"))
        assert actual == PHONE_VIEWPORT, f"/ops must run at {PHONE_VIEWPORT}, got {actual}"

    async def confirm_pickup(self, pur_number: str, pieces_by_awb: Mapping[str, str]) -> None:
        """Types actual pieces for each AWB on the PUR card, then confirms."""
        await self.assert_phone_viewport()
        await self.expect_visible(OpsIds.pickup_card(pur_number))
        for awb, pieces in pieces_by_awb.items():
            await self.fill(OpsIds.actual_pieces(pur_number, awb), pieces)
        await self.click(OpsIds.confirm(pur_number))
        modal_submit = self.by_testid(OpsIds.CONFIRM_SUBMIT)
        await modal_submit.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
        await self.click_locator(modal_submit)
        await self.by_testid(OpsIds.confirm(pur_number)).wait_for(
            state="hidden", timeout=MONEY_WRITE_TIMEOUT_MS
        )
