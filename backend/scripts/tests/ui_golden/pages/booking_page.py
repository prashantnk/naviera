"""
Booking wizards: B2C `/shipments/new/forward` and B2B `/b2b/shipments/new/forward`.

Both are two steps (form, then rate shopping). `book()` fills the form, picks a
quote card, reads the quoted ₹ total, submits, and returns the AWB/LR shown on
the shipment detail page the app lands on. The caller then asks the DbOracle
for the stored bill and asserts quote == stored == wallet debit.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from playwright.async_api import expect

from ..testids import BookingIds, ShipmentDetailIds
from ..ui_config import (
    ELEMENT_TIMEOUT_MS,
    MONEY_WRITE_TIMEOUT_MS,
    NAVIGATION_TIMEOUT_MS,
)
from .base_page import BasePage


@dataclass(frozen=True)
class PackageInput:
    """One package row (dimensions in cm, weight in kg)."""

    length_cm: str
    breadth_cm: str
    height_cm: str
    weight_kg: str
    box_count: str = "1"


@dataclass(frozen=True)
class BookingInput:
    """Everything a journey types into the booking form (labels as the user sees them)."""

    pickup_address_label: str
    delivery_name: str
    delivery_phone: str
    delivery_line1: str
    delivery_pincode: str
    delivery_city: str
    delivery_state: str
    category_label: str
    payment_mode_label: str
    goods_value: str
    service_option: str
    """`ServiceOption` value of the quote card to pick, e.g. `DELHIVERY_SURFACE`."""
    packages: List[PackageInput] = field(default_factory=list)
    is_cod: bool = False
    eway_bill: Optional[str] = None
    po_number: Optional[str] = None
    invoice_number: str = "INV-GOLDEN-001"
    """B2B only: every LR needs a GST invoice number (Delhivery One `b2b-order-creation`)."""
    carriers_risk: bool = False
    door_delivery: bool = False


@dataclass(frozen=True)
class BookingResult:
    """What the UI showed: the quoted total before submit and the AWB after."""

    awb: str
    quoted_total: Decimal


class _BookingPage(BasePage):
    """Shared steps of the B2C and B2B booking wizards."""

    async def open(self, route: Optional[str] = None) -> "_BookingPage":
        """Navigates to the booking wizard with clean draft state."""
        target_url = self.settings.url(route or self.ROUTE)
        try:
            await self.page.evaluate(
                "() => { for (let i = localStorage.length - 1; i >= 0; i--) { const k = localStorage.key(i); if (k && k.startsWith('shipment-draft-')) localStorage.removeItem(k); } }"
            )
        except Exception:
            pass
        await self.page.goto(target_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        cleared = False
        try:
            cleared = await self.page.evaluate(
                "() => { let c = false; for (let i = localStorage.length - 1; i >= 0; i--) { const k = localStorage.key(i); if (k && k.startsWith('shipment-draft-')) { localStorage.removeItem(k); c = true; } } return c; }"
            )
        except Exception:
            pass
        if cleared:
            await self.page.reload(wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        return self

    async def _fill_delivery(self, data: BookingInput) -> None:
        """Fills the consignee block."""
        await self.click(BookingIds.ADD_DELIVERY)
        await self.fill(BookingIds.DELIVERY_NAME, data.delivery_name)
        await self.fill(BookingIds.DELIVERY_PHONE, data.delivery_phone)
        await self.fill(BookingIds.DELIVERY_LINE1, data.delivery_line1)
        await self.fill(BookingIds.DELIVERY_PINCODE, data.delivery_pincode)
        # City/state are filled from the pincode lookup and may be read-only.
        for test_id, value in (
            (BookingIds.DELIVERY_CITY, data.delivery_city),
            (BookingIds.DELIVERY_STATE, data.delivery_state),
        ):
            field_locator = self.by_testid(test_id)
            if await field_locator.is_editable():
                await field_locator.fill(value)
        await self.click(BookingIds.DELIVERY_SAVE)

    async def _fill_packages(self, packages: List[PackageInput]) -> None:
        """Fills every package row; extra rows must already exist in the form."""
        for index, pkg in enumerate(packages):
            await self.fill(BookingIds.package_field(index, "length"), pkg.length_cm)
            await self.fill(BookingIds.package_field(index, "breadth"), pkg.breadth_cm)
            await self.fill(BookingIds.package_field(index, "height"), pkg.height_cm)
            await self.fill(BookingIds.package_field(index, "weight"), pkg.weight_kg)
            await self.fill(BookingIds.package_field(index, "boxes"), pkg.box_count)

    async def _fill_payment(self, data: BookingInput) -> None:
        """Fills payment mode, goods value (waiting for backend valuation) and COD toggle."""
        await self.select_option(BookingIds.PAYMENT_MODE, data.payment_mode_label)
        # Goods value first: wait for `/shipments/valuation` to populate `goods-total` before
        # toggling COD so `cod_amount` defaults to the evaluated total rather than 0.
        await self.fill(BookingIds.GOODS_VALUE, data.goods_value)
        await expect(self.by_testid(BookingIds.GOODS_TOTAL)).to_have_value(
            data.goods_value, timeout=ELEMENT_TIMEOUT_MS
        )
        cod = self.by_testid(BookingIds.COD_TOGGLE)
        if await cod.count() > 0 and await cod.is_checked() != data.is_cod:
            await self.click(BookingIds.COD_TOGGLE)

    async def _fill_common(self, data: BookingInput) -> None:
        """Fills pickup, consignee, category, packages and payment."""
        await self.select_option(BookingIds.PICKUP_ADDRESS, data.pickup_address_label)
        await self._fill_delivery(data)
        await self.select_option(BookingIds.CATEGORY, data.category_label)
        await self._fill_packages(data.packages)
        await self._fill_payment(data)

    async def _fill_extras(self, data: BookingInput) -> None:
        """Hook for flow-specific fields (B2B overrides it)."""

    async def _choose_quote_and_submit(self, service_option: str) -> BookingResult:
        """Goes to rate shopping, picks the quote card, reads its total and submits."""
        await self.click(BookingIds.NEXT)
        await self.click(BookingIds.quote_card(service_option))
        quoted_total = await self.money(BookingIds.QUOTE_TOTAL)
        await self.click(BookingIds.SUBMIT)
        awb_locator = self.by_testid(ShipmentDetailIds.AWB)
        await awb_locator.wait_for(state="visible", timeout=MONEY_WRITE_TIMEOUT_MS)
        return BookingResult(awb=(await awb_locator.inner_text()).strip(), quoted_total=quoted_total)

    async def open_quote_step(self, data: BookingInput) -> None:
        """Opens the wizard, fills step 1 and advances to the rate-shopping step."""
        await self.open()
        await self._fill_common(data)
        await self._fill_extras(data)
        await self.click(BookingIds.NEXT)

    async def book(self, data: BookingInput) -> BookingResult:
        """Runs the whole wizard and returns the AWB and the quoted ₹ total."""
        await self.open()
        await self._fill_common(data)
        await self._fill_extras(data)
        return await self._choose_quote_and_submit(data.service_option)


class B2CBookingPage(_BookingPage):
    """B2C forward booking."""

    ROUTE = "/shipments/new/forward"


class B2BBookingPage(_BookingPage):
    """B2B cargo LR booking (PO number, e-way bill, carrier's risk, door delivery)."""

    ROUTE = "/b2b/shipments/new/forward"

    async def _fill_extras(self, data: BookingInput) -> None:
        """Fills PO number, GST invoice number, e-way bill, carrier's risk and door delivery."""
        await self.click(BookingIds.ADD_INVOICE)
        await self.fill(BookingIds.invoice_number(0), data.invoice_number)
        if data.po_number:
            await self.fill(BookingIds.PO_NUMBER, data.po_number)
        if data.eway_bill:
            await self.click(BookingIds.ADD_EWAY_BILL)
            await self.fill(BookingIds.EWAY_BILL, data.eway_bill)
        risk = self.by_testid(BookingIds.CARRIERS_RISK)
        if await risk.is_checked() != data.carriers_risk:
            await self.click(BookingIds.CARRIERS_RISK)
        door = self.by_testid(BookingIds.DOOR_DELIVERY)
        if await door.is_checked() != data.door_delivery:
            await self.click(BookingIds.DOOR_DELIVERY)
