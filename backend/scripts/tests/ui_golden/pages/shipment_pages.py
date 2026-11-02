"""
Shipment detail, edit-with-preview and record-measurement (plan B14 screens).

Routes take the shipment UUID: B2C `/shipments/<id>`, B2B `/b2b/shipments/<id>`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..testids import MeasurementIds, ShipmentDetailIds, ShipmentEditIds, UpdateStatusIds
from ..ui_config import MONEY_WRITE_TIMEOUT_MS
from .base_page import BasePage

B2C_PREFIX = "/shipments"
B2B_PREFIX = "/b2b/shipments"


def shipment_route(shipment_id: str, is_b2b: bool, suffix: str = "") -> str:
    """Returns `/shipments/<id><suffix>` or `/b2b/shipments/<id><suffix>`."""
    prefix = B2B_PREFIX if is_b2b else B2C_PREFIX
    return f"{prefix}/{shipment_id}{suffix}"


@dataclass(frozen=True)
class RepricePreview:
    """The server preview the edit page shows before saving (display only)."""

    old_total: Decimal
    new_total: Decimal
    delta: Decimal
    note_type: str


class ShipmentDetailPage(BasePage):
    """One shipment's detail page."""

    async def open_shipment(self, shipment_id: str, is_b2b: bool = False) -> "ShipmentDetailPage":
        """Opens the detail page and waits for the AWB header."""
        await self.open(shipment_route(shipment_id, is_b2b))
        await self.expect_visible(ShipmentDetailIds.AWB)
        return self

    async def awb(self) -> str:
        """The AWB/LR shown in the header."""
        return await self.text_of(ShipmentDetailIds.AWB)

    async def status(self) -> str:
        """The status badge text."""
        return await self.text_of(ShipmentDetailIds.STATUS)

    async def charges_total(self) -> Decimal:
        """The ₹ total in the charges-history card."""
        return await self.money(ShipmentDetailIds.CHARGES_TOTAL)

    async def open_measurement_dialog(self) -> "MeasurementDialog":
        """Clicks "Record measurement" and returns the dialog object."""
        await self.click(ShipmentDetailIds.RECORD_MEASUREMENT)
        dialog = MeasurementDialog(self.page, self.settings, self.banner)
        await dialog.expect_visible(MeasurementIds.WEIGHT)
        return dialog

    async def update_status(
        self,
        status_label: str,
        comment: str,
        delivery_otp: Optional[str] = None,
        pod_received_by: Optional[str] = None,
        ndr_reason_label: Optional[str] = None,
    ) -> None:
        """Opens the Update Status dialog, fills it and submits (OTP + POD for Delivered)."""
        await self.click(ShipmentDetailIds.UPDATE_STATUS)
        await self.expect_visible(UpdateStatusIds.SUBMIT)
        await self.select_option(UpdateStatusIds.STATUS, status_label)
        await self.fill(UpdateStatusIds.COMMENT, comment)
        if delivery_otp:
            await self.fill(UpdateStatusIds.DELIVERY_OTP, delivery_otp)
        if pod_received_by:
            await self.fill(UpdateStatusIds.POD_RECEIVED_BY, pod_received_by)
        if ndr_reason_label:
            await self.select_option(UpdateStatusIds.NDR_REASON, ndr_reason_label)
        await self.click(UpdateStatusIds.SUBMIT)
        await self.by_testid(UpdateStatusIds.SUBMIT).wait_for(state="hidden", timeout=MONEY_WRITE_TIMEOUT_MS)


class MeasurementDialog(BasePage):
    """Record-measurement dialog (hub scale / rider entry)."""

    async def submit(
        self,
        weight_kg: str,
        length_cm: Optional[str] = None,
        breadth_cm: Optional[str] = None,
        height_cm: Optional[str] = None,
    ) -> None:
        """Enters the measured weight (and optional dimensions) and submits."""
        await self.fill(MeasurementIds.WEIGHT, weight_kg)
        for test_id, value in (
            (MeasurementIds.LENGTH, length_cm),
            (MeasurementIds.BREADTH, breadth_cm),
            (MeasurementIds.HEIGHT, height_cm),
        ):
            if value is not None:
                await self.fill(test_id, value)
        await self.click(MeasurementIds.SUBMIT)
        await self.by_testid(MeasurementIds.SUBMIT).wait_for(state="hidden", timeout=MONEY_WRITE_TIMEOUT_MS)


class ShipmentEditPage(BasePage):
    """Edit page that asks the server for a re-price preview before saving."""

    async def open_edit(self, shipment_id: str, is_b2b: bool = False) -> "ShipmentEditPage":
        """Opens `/<prefix>/<id>/edit`."""
        await self.open(shipment_route(shipment_id, is_b2b, "/edit"))
        await self.expect_visible(ShipmentEditIds.SAVE)
        return self

    async def set_package_weight(self, index: int, weight_kg: str) -> None:
        """Changes one package's weight (triggers the server preview)."""
        await self.fill(ShipmentEditIds.package_field(index, "weight"), weight_kg)

    async def read_preview(self) -> RepricePreview:
        """Waits for the preview panel and reads old/new totals, delta and note type."""
        await self.expect_visible(ShipmentEditIds.PREVIEW_DELTA)
        return RepricePreview(
            old_total=await self.money(ShipmentEditIds.PREVIEW_OLD_TOTAL),
            new_total=await self.money(ShipmentEditIds.PREVIEW_NEW_TOTAL),
            delta=await self.money(ShipmentEditIds.PREVIEW_DELTA),
            note_type=await self.text_of(ShipmentEditIds.PREVIEW_NOTE_TYPE),
        )

    async def save(self) -> None:
        """Saves; the app returns to the detail page."""
        await self.click(ShipmentEditIds.SAVE)
        await self.page.wait_for_url(lambda url: not url.rstrip("/").endswith("/edit"))
