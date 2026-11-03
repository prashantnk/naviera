"""
UI pricing journeys (Pricing Redesign Step D9, `llm_resources/.agents/pricing/DESIGN.md` §D):
1. Delhivery unavailable state (`FAKE_UNSERVICEABLE_PINS` -> disabled option cards + reason).
2. 409 `PRICE_CHANGED` dialog on Book -> confirm new server price -> booked at new total.
3. Admin Prime lane inline edit + Pricing policy panel on `/settings/prime-lanes`.
4. B2B Prime quote -> book with `door_delivery=True` (`PRIME_SURFACE`), verifying screen ₹ == DB ₹.
5. Ops AWB + Delhivery charged weight/amount entry -> backend billing gap alert & gap ₹ badge.
"""

import re
import uuid
from decimal import Decimal
from typing import Dict

import pytest

pytest.importorskip("playwright.async_api")

from golden_journeys.golden_env import (  # noqa: E402
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    OPERATIONS_EMAIL,
)
from playwright.async_api import Page, Route, expect  # noqa: E402

from app.models.pickups import ServiceOption  # noqa: E402

from .db_oracle import DbOracle  # noqa: E402
from .money import to_paisa  # noqa: E402
from .pages.base_page import BasePage  # noqa: E402
from .pages.booking_page import (  # noqa: E402
    B2BBookingPage,
    B2CBookingPage,
    BookingInput,
    PackageInput,
)
from .pages.shipment_pages import ShipmentDetailPage  # noqa: E402
from .testids import (  # noqa: E402
    BookingIds,
    CarrierBillingIds,
    PricingPolicyIds,
    PrimeLanesIds,
    ShipmentDetailIds,
)
from .ui_config import (  # noqa: E402
    DESKTOP,
    ELEMENT_TIMEOUT_MS,
    MONEY_WRITE_TIMEOUT_MS,
    rewrite_api_url,
)
from .ui_fixtures import TabFactory, UiSettings, api_url  # noqa: E402

JOURNEY = "PRICING-D9"
B2C_PICKUP_LABEL = "LogiSmart B2C Gurugram Hub Warehouse"
B2B_PICKUP_LABEL = "B2B Dock Manager"
UNSERVICEABLE_PINCODE = "999999"
SERVICEABLE_B2C_PINCODE = "110001"
SERVICEABLE_B2B_PINCODE = "400001"
STALE_DISPLAY_TOTAL = Decimal("80.00")
QUOTES_URL_RE = re.compile(r"/api/v1/quotes(\?.*)?$")
SHIPMENTS_URL_RE = re.compile(r"/api/v1/shipments(\?.*)?$")
PRIME_LANES_ROUTE = "/settings/prime-lanes"
CARRIER_CHARGED_WEIGHT_KG = "2.5"
CARRIER_CHARGED_AMOUNT_INR = "500.00"


def _b2c_input(pincode: str) -> BookingInput:
    """Prepaid 1 kg B2C parcel from Gurugram to `pincode` on Delhivery Surface."""
    return BookingInput(
        pickup_address_label=B2C_PICKUP_LABEL,
        delivery_name="Riya Sharma",
        delivery_phone="9876543210",
        delivery_line1="12 Connaught Place",
        delivery_pincode=pincode,
        delivery_city="New Delhi",
        delivery_state="DL",
        category_label="Electronics & Gadgets",
        payment_mode_label="Prepaid",
        goods_value="2000",
        service_option=ServiceOption.DELHIVERY_SURFACE.value,
        packages=[PackageInput("10", "10", "10", "1", "1")],
        is_cod=False,
    )


def _b2b_door_delivery_input() -> BookingInput:
    """Prepaid B2B LR Gurugram -> Mumbai on Logismart Prime with door delivery ticked."""
    return BookingInput(
        pickup_address_label=B2B_PICKUP_LABEL,
        delivery_name="Mumbai Industrial Co",
        delivery_phone="9876543211",
        delivery_line1="88 Nariman Point",
        delivery_pincode=SERVICEABLE_B2B_PINCODE,
        delivery_city="Mumbai",
        delivery_state="MH",
        category_label="Apparel & Clothing",
        payment_mode_label="Prepaid",
        goods_value="10000",
        service_option=ServiceOption.PRIME_SURFACE.value,
        packages=[PackageInput("20", "20", "20", "5", "2")],
        po_number="PO-D9-01",
        eway_bill="123456789012",
        carriers_risk=False,
        door_delivery=True,
    )


async def _intercept_quote_with_stale_total(
    page: Page, stale_total: Decimal
) -> Dict[str, Decimal]:
    """
    Rewrites the first `/api/v1/quotes` response so `DELHIVERY_SURFACE` displays `stale_total`
    while recording the real server `total_amount` in the returned dict (`recorded["real"]`).
    When the user clicks Book, the real backend sees `expected_total != real` and returns 409.
    """
    recorded: Dict[str, Decimal] = {}

    async def _handler(route: Route) -> None:
        resp = await route.fetch(url=rewrite_api_url(route.request.url, api_url()))
        body = await resp.json()
        for option in body.get("options", []):
            if option.get("service_option") == ServiceOption.DELHIVERY_SURFACE.value:
                recorded["real"] = to_paisa(option["total_amount"])
                option["total_amount"] = float(stale_total)
        await route.fulfill(response=resp, json=body)

    await page.route(QUOTES_URL_RE, _handler)
    return recorded


@pytest.mark.ui
async def test_ui_d9_unavailable_and_price_changed_and_carrier_gap(
    role_tabs: TabFactory, ui_settings: UiSettings, step_banner, db_oracle: DbOracle
) -> None:
    """
    Exercises:
    1. Delhivery unavailable cards (`999999` -> disabled cards + reason + submit disabled).
    2. 409 `PRICE_CHANGED` dialog -> confirm new total -> shipment booked at new total.
    3. Ops enters Delhivery AWB + higher charged amount -> billing gap badge & ₹ gap alert.
    """
    b2c_tab = await role_tabs.as_role(CUSTOMER_B2C_EMAIL, DESKTOP)
    ops_tab = await role_tabs.as_role(OPERATIONS_EMAIL, DESKTOP)
    booking = B2CBookingPage(b2c_tab.page, ui_settings, step_banner)

    # 1. Unserviceable destination pincode -> option cards disabled with reason.
    await step_banner.show(b2c_tab.page, JOURNEY, 1, 3, "Unserviceable pincode shows unavailable cards")
    await booking.open_quote_step(_b2c_input(UNSERVICEABLE_PINCODE))
    await booking.expect_visible(BookingIds.QUOTE_NONE_AVAILABLE)
    reason_locator = booking.by_testid(BookingIds.QUOTE_UNAVAILABLE_REASON).first
    await expect(reason_locator).to_be_visible(timeout=ELEMENT_TIMEOUT_MS)
    await expect(reason_locator).to_contain_text(UNSERVICEABLE_PINCODE)
    await expect(
        booking.by_testid(BookingIds.quote_card(ServiceOption.DELHIVERY_SURFACE.value))
    ).to_be_disabled()
    await expect(
        booking.by_testid(BookingIds.quote_card(ServiceOption.DELHIVERY_EXPRESS.value))
    ).to_be_disabled()
    await expect(booking.by_testid(BookingIds.SUBMIT)).to_be_disabled()

    # 2. 409 PRICE_CHANGED flow: quote shows stale ₹80.00, Book triggers 409 dialog, confirm books at real total.
    await step_banner.show(b2c_tab.page, JOURNEY, 2, 3, "409 PRICE_CHANGED dialog on Book -> confirm")
    b2c_tab.guard.expect_http(SHIPMENTS_URL_RE, 409)
    b2c_tab.guard.expect_console(r"status of 409")
    recorded = await _intercept_quote_with_stale_total(b2c_tab.page, STALE_DISPLAY_TOTAL)
    try:
        await booking.open_quote_step(_b2c_input(SERVICEABLE_B2C_PINCODE))
        await booking.click(BookingIds.quote_card(ServiceOption.DELHIVERY_SURFACE.value))
        assert await booking.money(BookingIds.QUOTE_TOTAL) == STALE_DISPLAY_TOTAL
        await booking.click(BookingIds.SUBMIT)

        await booking.expect_visible(BookingIds.PRICE_CHANGED)
        assert await booking.money(BookingIds.PRICE_CHANGED_OLD) == STALE_DISPLAY_TOTAL
        real_total = recorded["real"]
        assert await booking.money(BookingIds.PRICE_CHANGED_NEW) == real_total

        await booking.click(BookingIds.PRICE_CHANGED_CONFIRM)
        awb_locator = booking.by_testid(ShipmentDetailIds.AWB)
        await awb_locator.wait_for(state="visible", timeout=MONEY_WRITE_TIMEOUT_MS)
        awb = (await awb_locator.inner_text()).strip()
    finally:
        await b2c_tab.page.unroute(QUOTES_URL_RE)

    stored = await db_oracle.shipment(awb)
    assert stored.total_logistics_cost == real_total

    # 3. Ops enters Delhivery AWB + charged weight/amount -> billing gap badge & ₹ gap amount.
    await step_banner.show(ops_tab.page, JOURNEY, 3, 3, "Ops records Delhivery AWB and billing gap")
    detail = ShipmentDetailPage(ops_tab.page, ui_settings, step_banner)
    await detail.open_shipment(str(stored.shipment_id), is_b2b=False)
    await detail.expect_visible(CarrierBillingIds.PANEL)
    await detail.click(CarrierBillingIds.EDIT)

    carrier_awb = f"DLV-{uuid.uuid4().hex[:10].upper()}"
    await detail.fill(CarrierBillingIds.FORM_AWB, carrier_awb)
    await detail.fill(CarrierBillingIds.FORM_CHARGED_WEIGHT, CARRIER_CHARGED_WEIGHT_KG)
    await detail.fill(CarrierBillingIds.FORM_CHARGED_AMOUNT, CARRIER_CHARGED_AMOUNT_INR)
    await detail.click(CarrierBillingIds.FORM_SUBMIT)

    await detail.expect_visible(CarrierBillingIds.GAP_ALERT)
    await detail.expect_visible(CarrierBillingIds.GAP_BADGE)
    assert await detail.text_of(CarrierBillingIds.AWB) == carrier_awb
    gap_shown = await detail.money(CarrierBillingIds.GAP_AMOUNT)
    assert gap_shown > Decimal("0.00")


@pytest.mark.ui
async def test_ui_d9_admin_prime_lane_edit_and_b2b_door_delivery(
    role_tabs: TabFactory, ui_settings: UiSettings, step_banner, db_oracle: DbOracle
) -> None:
    """
    Exercises:
    1. Admin opens `/settings/prime-lanes`, sees Pricing policy panel + Prime lanes table,
       inline-edits a lane's `rate_per_kg` and restores it.
    2. Customer B2B books a `PRIME_SURFACE` LR with `door_delivery=True`, verifying screen ₹ == DB ₹.
    """
    admin_tab = await role_tabs.as_role(ADMIN_EMAIL, DESKTOP)
    b2b_tab = await role_tabs.as_role(CUSTOMER_B2B_EMAIL, DESKTOP)

    # 1. Admin views Pricing policy panel on `/settings` then clicks through to `/settings/prime-lanes`
    #    to inline-edit a Prime lane.
    await step_banner.show(admin_tab.page, JOURNEY, 1, 2, "Admin edits a Prime lane on /settings/prime-lanes")
    settings_page = BasePage(admin_tab.page, ui_settings, step_banner)
    await settings_page.open("/settings")
    await settings_page.click_locator(admin_tab.page.get_by_role("button", name="Pricing").first)
    await settings_page.expect_visible(PricingPolicyIds.PANEL)
    await settings_page.expect_visible(PricingPolicyIds.DELHIVERY_MARKUP)
    await settings_page.click(PricingPolicyIds.PRIME_LANES_LINK)

    await settings_page.expect_visible(PrimeLanesIds.PAGE)
    await settings_page.expect_visible(PrimeLanesIds.TABLE)

    first_row = admin_tab.page.locator('tr[data-testid^="prime-lanes.row."]').first
    await first_row.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
    row_testid = await first_row.get_attribute("data-testid")
    assert row_testid is not None
    lane_id = row_testid.removeprefix("prime-lanes.row.")

    await settings_page.click(PrimeLanesIds.row_edit(lane_id))
    rate_input = settings_page.by_testid(PrimeLanesIds.row_field(lane_id, "rate_per_kg"))
    original_rate = await rate_input.input_value()
    temp_rate = str(Decimal(original_rate) + Decimal("1"))

    await settings_page.fill(PrimeLanesIds.row_field(lane_id, "rate_per_kg"), temp_rate)
    await settings_page.click(PrimeLanesIds.row_save(lane_id))
    await settings_page.expect_visible(PrimeLanesIds.row_edit(lane_id))

    # Restore original rate so seeded fixture lanes stay unchanged for subsequent journeys.
    await settings_page.click(PrimeLanesIds.row_edit(lane_id))
    await settings_page.fill(PrimeLanesIds.row_field(lane_id, "rate_per_kg"), original_rate)
    await settings_page.click(PrimeLanesIds.row_save(lane_id))
    await settings_page.expect_visible(PrimeLanesIds.row_edit(lane_id))

    # 2. B2B customer books a Prime LR with Door Delivery ticked.
    await step_banner.show(b2b_tab.page, JOURNEY, 2, 2, "B2B customer books Prime LR with door delivery")
    b2b_booking = B2BBookingPage(b2b_tab.page, ui_settings, step_banner)
    lr = await b2b_booking.book(_b2b_door_delivery_input())
    stored_lr = await db_oracle.shipment(lr.awb)
    assert lr.quoted_total == stored_lr.total_logistics_cost
