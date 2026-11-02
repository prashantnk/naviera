"""
Pickup requests list + confirm-pickup (dispatch) dialog with actual pieces (plan B5/B14).

B2C `/pickup-requests`, B2B `/b2b/pickup-requests`.
"""

from dataclasses import dataclass
from typing import List, Mapping, Sequence

from ..testids import PickupDispatchIds, PickupRequestsIds
from ..ui_config import MONEY_WRITE_TIMEOUT_MS
from .base_page import BasePage

B2C_ROUTE = "/pickup-requests"
B2B_ROUTE = "/b2b/pickup-requests"


@dataclass(frozen=True)
class PickedLine:
    """One LR/AWB at the door: picked or not, and how many boxes were actually handed over."""

    awb: str
    picked: bool = True
    actual_pieces: str = ""


class PickupRequestsPage(BasePage):
    """Pickup request list (row actions open the dispatch dialog)."""

    ROUTE = B2C_ROUTE

    async def open_flow(self, is_b2b: bool = False) -> "PickupRequestsPage":
        """Opens the B2C or B2B list."""
        await self.open(B2B_ROUTE if is_b2b else B2C_ROUTE)
        return self

    async def open_dispatch(self, pur_number: str) -> "PickupDispatchDialog":
        """Clicks "Confirm picked up" on one PUR row and returns the dialog."""
        await self.click(PickupRequestsIds.confirm_picked(pur_number))
        dialog = PickupDispatchDialog(self.page, self.settings, self.banner)
        await dialog.expect_visible(PickupDispatchIds.CONFIRM)
        return dialog


class PickupDispatchDialog(BasePage):
    """Checklist of LRs with a picked checkbox and an actual-pieces input per row."""

    async def set_lines(self, lines: Sequence[PickedLine]) -> None:
        """Ticks/unticks each AWB and types actual pieces where given."""
        for line in lines:
            box = self.by_testid(PickupDispatchIds.picked(line.awb))
            if await box.is_checked() != line.picked:
                await self.click(PickupDispatchIds.picked(line.awb))
            if line.picked and line.actual_pieces:
                await self.fill(PickupDispatchIds.actual_pieces(line.awb), line.actual_pieces)

    async def confirm(self) -> None:
        """Confirms the pickup and waits for the dialog to close."""
        await self.click(PickupDispatchIds.CONFIRM)
        await self.by_testid(PickupDispatchIds.CONFIRM).wait_for(state="hidden", timeout=MONEY_WRITE_TIMEOUT_MS)

    async def dispatch(self, lines: Sequence[PickedLine]) -> None:
        """`set_lines` + `confirm` in one call."""
        await self.set_lines(lines)
        await self.confirm()


def lines_from_pieces(pieces_by_awb: Mapping[str, str]) -> List[PickedLine]:
    """Builds picked lines from `{awb: actual_pieces}`."""
    return [PickedLine(awb=awb, actual_pieces=pieces) for awb, pieces in pieces_by_awb.items()]
