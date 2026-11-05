"""
Single source of the `data-testid` names the UI layer uses.

Convention (agreed with @reprice-ui on the swarm board):
`<page>.<section>.<element>`, lowercase, kebab-case inside each part, dynamic
ids last (`shipments.row.<awb>`). Money elements carry the testid on the node
whose text is exactly the formatted amount (`₹1,234.50`) and nothing else.

Frontend workers add these attributes in the screens they own (wave 1 for edit,
detail, dispatch, /ops, weight mismatch; E5 for the rest). Keeping the names in
one module means a rename is one edit here plus one in the TSX.
"""

import re

TESTID_RE = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[A-Za-z0-9_-]+)+$"
)
"""The first two parts are lowercase kebab-case; later parts may carry a raw id (AWB, PUR)."""


def testid(*parts: str) -> str:
    """
    Joins parts into one testid and validates the convention.

    `testid("pickup-dispatch", "row", "LOGISMART-TEST-AB12CD34")` gives
    `"pickup-dispatch.row.LOGISMART-TEST-AB12CD34"`. Dynamic ids are kept exactly
    as the screen shows them, so the TSX can interpolate the raw value.

    Raises:
        ValueError: When the result does not follow `<page>.<section>.<element>`.
    """
    value = ".".join(p.strip() for p in parts)
    if not TESTID_RE.match(value):
        raise ValueError(f"Bad data-testid {value!r}: use <page>.<section>.<element>")
    return value


# `testid` starts with "test"; stop pytest from collecting it when a test module imports it.
testid.__test__ = False  # type: ignore[attr-defined]


class LoginIds:
    """Login page. These three predate the convention and are used as they are."""

    TAB_SIGNIN = "tab-signin"
    TAB_OTP = "tab-otp"
    TAB_SIGNUP = "tab-signup"
    EMAIL_INPUT_ID = "email-pw"
    PASSWORD_INPUT_ID = "password-signin"


class AppShellIds:
    """Header elements present on every authenticated page."""

    WALLET_BALANCE = "wallet.header.balance"


class AuthIds:
    """`AuthGuard`'s "Access not available" screen (lost / missing tenant membership)."""

    ACCESS_DENIED = "auth.access-denied"
    ACCESS_DENIED_SIGN_OUT = "auth.access-denied.sign-out"


class BookingIds:
    """B2C (`/shipments/new/forward`) and B2B (`/b2b/shipments/new/forward`) booking."""

    PICKUP_ADDRESS = "booking.pickup.address-select"
    ADD_DELIVERY = "booking.delivery.add-new"
    DELIVERY_NAME = "booking.delivery.name"
    DELIVERY_PHONE = "booking.delivery.phone"
    DELIVERY_LINE1 = "booking.delivery.address-line1"
    DELIVERY_PINCODE = "booking.delivery.pincode"
    DELIVERY_CITY = "booking.delivery.city"
    DELIVERY_STATE = "booking.delivery.state"
    DELIVERY_SAVE = "booking.delivery.save"
    CATEGORY = "booking.shipment.category"
    PAYMENT_MODE = "booking.payment.mode"
    COD_TOGGLE = "booking.payment.cod-toggle"
    COD_UNAVAILABLE_NOTE = "booking.payment.cod-unavailable"
    GOODS_VALUE = "booking.payment.goods-value"
    GOODS_TOTAL = "booking.payment.goods-total"
    ADD_EWAY_BILL = "booking.payment.add-eway-bill"
    ADD_INVOICE = "booking.payment.add-invoice"
    INVOICE_ERROR = "booking.payment.invoice-error"
    EWAY_BILL = "booking.payment.eway-bill"
    PO_NUMBER = "booking.shipment.po-number"
    CARRIERS_RISK = "booking.shipment.carriers-risk"
    DOOR_DELIVERY = "booking.shipment.door-delivery"
    NEXT = "booking.actions.next"
    QUOTE_TOTAL = "booking.quote.total"
    QUOTE_SHIPPING = "booking.quote.shipping"
    QUOTE_DOOR_COLLECT = "booking.quote.door-collect"
    QUOTE_REMITTANCE = "booking.quote.remittance"
    QUOTE_CACHED = "booking.quote.cached"
    QUOTE_UNAVAILABLE_REASON = "booking.quote.unavailable-reason"
    QUOTE_NONE_AVAILABLE = "booking.quote.none-available"
    PRICE_CHANGED = "booking.price-changed"
    PRICE_CHANGED_OLD = "booking.price-changed.old"
    PRICE_CHANGED_NEW = "booking.price-changed.new"
    PRICE_CHANGED_CONFIRM = "booking.price-changed.confirm"
    SUBMIT = "booking.actions.submit"

    @staticmethod
    def package_field(index: int, field: str) -> str:
        """`booking.package.<field>-<index>`, e.g. `booking.package.weight-0`."""
        return testid("booking", "package", f"{field}-{index}")

    @staticmethod
    def invoice_number(index: int) -> str:
        """`booking.payment.invoice-number-<index>` (B2B GST invoice rows)."""
        return testid("booking", "payment", f"invoice-number-{index}")

    @staticmethod
    def quote_card(service_option: str) -> str:
        """`booking.quote.card-<option>`, e.g. `booking.quote.card-delhivery-surface`."""
        return testid("booking", "quote", f"card-{service_option.lower().replace('_', '-')}")


class ShipmentEditIds:
    """`/shipments/[id]/edit` and `/b2b/shipments/[id]/edit` with the server preview."""

    PREVIEW_DELTA = "shipment-edit.preview.delta"
    PREVIEW_NEW_TOTAL = "shipment-edit.preview.new-total"
    PREVIEW_OLD_TOTAL = "shipment-edit.preview.old-total"
    PREVIEW_NOTE_TYPE = "shipment-edit.preview.note-type"
    SAVE = "shipment-edit.actions.save"

    @staticmethod
    def package_field(index: int, field: str) -> str:
        """`shipment-edit.form.<field>-<index>`, e.g. `shipment-edit.form.weight-0`."""
        return testid("shipment-edit", "form", f"{field}-{index}")


class ShipmentDetailIds:
    """`/shipments/[id]` and `/b2b/shipments/[id]`."""

    AWB = "shipment-detail.header.awb"
    STATUS = "shipment-detail.header.status"
    CHARGES_TOTAL = "shipment-detail.charges.total"
    RECORD_MEASUREMENT = "shipment-detail.actions.record-measurement"
    DOWNLOAD_LABEL = "shipment-detail.actions.download-label"
    DOWNLOAD_INVOICE = "shipment-detail.actions.download-invoice"
    CANCEL = "shipment-detail.actions.cancel"
    UPDATE_STATUS = "shipment-detail.actions.update-status"

    @staticmethod
    def charges_row(n: int) -> str:
        """`shipment-detail.charges.row-<n>` (0 = oldest adjustment)."""
        return testid("shipment-detail", "charges", f"row-{n}")


class UpdateStatusIds:
    """`/shipments/[id]` operations status update dialog."""
    STATUS = "update-status.form.status"
    COMMENT = "update-status.form.comment"
    DELIVERY_OTP = "update-status.form.delivery-otp"
    POD_RECEIVED_BY = "update-status.form.pod-received-by"
    NDR_REASON = "update-status.form.ndr-reason"
    IS_PUBLIC = "update-status.form.is-public"
    SUBMIT = "update-status.actions.submit"


class MeasurementIds:
    """Record-measurement dialog (replaces "Audit Scale")."""

    WEIGHT = "measurement.form.weight"
    LENGTH = "measurement.form.length"
    BREADTH = "measurement.form.breadth"
    HEIGHT = "measurement.form.height"
    SUBMIT = "measurement.actions.submit"


class PickupRequestsIds:
    """Pickup request list rows."""

    @staticmethod
    def confirm_picked(pur: str) -> str:
        """`pickup-requests.row.<pur>.confirm-picked` row action."""
        return testid("pickup-requests", "row", pur, "confirm-picked")


class PickupDispatchIds:
    """Confirm-pickup dialog on `/pickup-requests` and `/b2b/pickup-requests`."""

    CONFIRM = "pickup-dispatch.actions.confirm"
    OTP_INPUT = "pickup-dispatch.otp-input"
    OVERRIDE_TOGGLE = "pickup-dispatch.override-toggle"
    OVERRIDE_REASON = "pickup-dispatch.override-reason"
    ERROR = "pickup-dispatch.error"

    @staticmethod
    def row(awb: str) -> str:
        """`pickup-dispatch.row.<awb>`."""
        return testid("pickup-dispatch", "row", awb)

    @staticmethod
    def picked(awb: str) -> str:
        """`pickup-dispatch.row.<awb>.picked` checkbox."""
        return testid("pickup-dispatch", "row", awb, "picked")

    @staticmethod
    def actual_pieces(awb: str) -> str:
        """`pickup-dispatch.row.<awb>.actual-pieces` number input."""
        return testid("pickup-dispatch", "row", awb, "actual-pieces")


class OpsIds:
    """Mobile `/ops` My Pickups cards (390x844)."""

    @staticmethod
    def pickup_card(pur: str) -> str:
        """`ops.pickup-card.<pur>`."""
        return testid("ops", "pickup-card", pur)

    @staticmethod
    def actual_pieces(pur: str, awb: str) -> str:
        """`ops.pickup-card.<pur>.actual-pieces-<awb>`."""
        return testid("ops", "pickup-card", pur, f"actual-pieces-{awb}")

    @staticmethod
    def confirm(pur: str) -> str:
        """`ops.pickup-card.<pur>.confirm`."""
        return testid("ops", "pickup-card", pur, "confirm")

    CONFIRM_OTP_INPUT = "ops.pickup-confirm.otp-input"
    CONFIRM_OVERRIDE_TOGGLE = "ops.pickup-confirm.override-toggle"
    CONFIRM_OVERRIDE_REASON = "ops.pickup-confirm.override-reason"
    CONFIRM_ERROR = "ops.pickup-confirm.error"
    CONFIRM_SUBMIT = "ops.pickup-confirm.submit"


class WalletIds:
    """`/wallet`."""

    BALANCE = "wallet.summary.balance"
    RECHARGE = "wallet.actions.recharge"

    @staticmethod
    def txn_row(receipt: str) -> str:
        """`wallet.txn.<receipt>` ledger row."""
        return testid("wallet", "txn", receipt)

    @staticmethod
    def txn_amount(receipt: str) -> str:
        """`wallet.txn.<receipt>.amount`."""
        return testid("wallet", "txn", receipt, "amount")


class InvoiceIds:
    """`/finances/invoices` (invoices, debit notes, credit notes)."""

    TAB_ALL = "invoices.tabs.all"
    TAB_INVOICES = "invoices.tabs.invoices"
    TAB_DEBIT = "invoices.tabs.debit-notes"
    TAB_CREDIT = "invoices.tabs.credit-notes"
    DOWNLOAD_PDF = "invoice-detail.actions.download-pdf"

    @staticmethod
    def row(number: str) -> str:
        """`invoices.row.<number>`."""
        return testid("invoices", "row", number)

    @staticmethod
    def row_total(number: str) -> str:
        """`invoices.row.<number>.total`."""
        return testid("invoices", "row", number, "total")


class WeightMismatchIds:
    """`/disputes/weight-mismatch`."""

    CLAIM_WEIGHT = "weight-mismatch.claim.weight"
    CLAIM_REMARKS = "weight-mismatch.claim.remarks"
    CLAIM_SUBMIT = "weight-mismatch.claim.submit"

    @staticmethod
    def row(awb: str) -> str:
        """`weight-mismatch.row.<awb>`."""
        return testid("weight-mismatch", "row", awb)

    @staticmethod
    def raise_claim(awb: str) -> str:
        """`weight-mismatch.row.<awb>.raise-claim`."""
        return testid("weight-mismatch", "row", awb, "raise-claim")

    @staticmethod
    def cost_diff(awb: str) -> str:
        """`weight-mismatch.row.<awb>.cost-diff` (₹ delta)."""
        return testid("weight-mismatch", "row", awb, "cost-diff")


class RemittanceIds:
    """`/finances/remittances`."""

    DOWNLOAD_CSV = "remittance-detail.actions.download-csv"

    @staticmethod
    def row(number: str) -> str:
        """`remittances.row.<number>`."""
        return testid("remittances", "row", number)

    @staticmethod
    def row_total(number: str) -> str:
        """`remittances.row.<number>.total`."""
        return testid("remittances", "row", number, "total")


class PricingPolicyIds:
    """`/settings` Pricing tab and `/settings/prime-lanes` pricing policy panel."""

    PANEL = "pricing-policy.panel"
    DELHIVERY_MARKUP = "pricing-policy.markup.DELHIVERY_SURFACE.value"
    COD_MIN = "pricing-policy.cod-min"
    COD_PERCENT = "pricing-policy.cod-percent"
    SAVE = "pricing-policy.save"
    CONFIRM_DIALOG = "pricing-policy.confirm-dialog"
    CONFIRM_SAVE = "pricing-policy.confirm-save"
    PRIME_LANES_LINK = "pricing-policy.prime-lanes-link"


class PrimeLanesIds:
    """`/settings/prime-lanes` Prime lane table and inline row editor."""

    PAGE = "prime-lanes.page"
    TABLE = "prime-lanes.table"

    @staticmethod
    def row(lane_id: str) -> str:
        """`prime-lanes.row.<lane_id>`."""
        return testid("prime-lanes", "row", lane_id)

    @staticmethod
    def row_edit(lane_id: str) -> str:
        """`prime-lanes.row.<lane_id>.edit`."""
        return testid("prime-lanes", "row", lane_id, "edit")

    @staticmethod
    def row_field(lane_id: str, field: str) -> str:
        """`prime-lanes.row.<lane_id>.<field>`, e.g. `rate_per_kg`."""
        return testid("prime-lanes", "row", lane_id, field)

    @staticmethod
    def row_save(lane_id: str) -> str:
        """`prime-lanes.row.<lane_id>.save`."""
        return testid("prime-lanes", "row", lane_id, "save")


class CarrierBillingIds:
    """`CarrierBillingPanel` on `/shipments/[id]` and `/b2b/shipments/[id]`."""

    PANEL = "carrier-billing"
    EDIT = "carrier-billing.edit"
    SERVICE_OPTION = "carrier-billing.service-option"
    AWB = "carrier-billing.awb"
    CHARGED_WEIGHT = "carrier-billing.charged-weight"
    CHARGED_AMOUNT = "carrier-billing.charged-amount"
    GAP_ALERT = "carrier-billing.gap-alert"
    GAP_BADGE = "carrier-billing.gap-badge"
    GAP_AMOUNT = "carrier-billing.gap-amount"
    GAP_MESSAGE = "carrier-billing.gap-message"
    NO_GAP_BADGE = "carrier-billing.no-gap-badge"
    FORM_AWB = "carrier-billing.form.awb"
    FORM_CHARGED_WEIGHT = "carrier-billing.form.charged-weight"
    FORM_CHARGED_AMOUNT = "carrier-billing.form.charged-amount"
    FORM_SUBMIT = "carrier-billing.form.submit"
