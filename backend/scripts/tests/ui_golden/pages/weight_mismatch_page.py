"""`/disputes/weight-mismatch`: audited rows and the Raise Claim dialog."""

from decimal import Decimal

from ..testids import WeightMismatchIds
from ..ui_config import MONEY_WRITE_TIMEOUT_MS
from .base_page import BasePage


class WeightMismatchPage(BasePage):
    """Weight mismatch list."""

    ROUTE = "/disputes/weight-mismatch"

    async def cost_diff(self, awb: str) -> Decimal:
        """The ₹ difference charged for this AWB."""
        return await self.money(WeightMismatchIds.cost_diff(awb))

    async def raise_claim(self, awb: str, claimed_weight_g: str, remarks: str) -> None:
        """Opens Raise Claim on the row, fills weight (grams) and remarks, and submits."""
        await self.click(WeightMismatchIds.raise_claim(awb))
        await self.fill(WeightMismatchIds.CLAIM_WEIGHT, claimed_weight_g)
        await self.fill(WeightMismatchIds.CLAIM_REMARKS, remarks)
        await self.click(WeightMismatchIds.CLAIM_SUBMIT)
        await self.by_testid(WeightMismatchIds.CLAIM_SUBMIT).wait_for(state="hidden", timeout=MONEY_WRITE_TIMEOUT_MS)
