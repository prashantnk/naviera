
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import httpx
from httpx import ASGITransport
from sqlmodel import col, select

from app.core.money import to_money as M
from app.main import app
from app.models.delhivery_modules import BillingInvoice, InvoiceNoteType
from app.models.pickups import (
    CodRemittanceStatus,
    FreightPaymentMode,
    NdrAction,
    NdrExceptionReason,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ServiceType,
)
from app.models.repricing import (
    BillingChannel,
    ChargeAdjustmentReason,
    ShipmentChargeAdjustment,
    ShipmentMeasurement,
)
from app.models.tenants import Tenant
from app.models.wallet import (
    UserWallet,
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
)
from app.services.delhivery_modules import format_document_number

from .golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    OPERATIONS_EMAIL,
    GoldenSessionLocal,
    allow_to_pay_bookings,
    document_prefix,
    find_seeded_address_id,
    get_wallet_balance,
    headers,
    load_accounts,
    order_ref,
    read_otp_as_merchant,
    resolve_golden_slug,
)

"""
Golden Test Suite 11 (J56-J63): Lifecycle, NDR and RTO rules.

Phase C plan:
- forward with Out for delivery
- 3 NDRs -> auto-RTO, RTO_FREIGHT + DN, COD-fee CN
- RTO legs to RTO_DELIVERED
- TO_PAY billed to merchant on refused
- customer POSTPAID RTO billed through wallet
- cancel in transit -> RTO
- LOST refund
- transition check matrix
"""

BILLING_CHANNEL_KEY = "billing_channel"
CHANNEL_WALLET = BillingChannel.WALLET.value
CHANNEL_NONE = BillingChannel.NONE.value

MAX_GST_SPLIT_SKEW = Decimal("0.01")
MAX_DOCUMENT_NUMBER_LENGTH = 16

BILL_DEBIT_TYPES = frozenset(
    {
        WalletTxnType.SPEND,
        WalletTxnType.WEIGHT_AUDIT_DEBIT,
        WalletTxnType.RTO_FREIGHT,
        WalletTxnType.FREIGHT_COLLECTION,
    }
)
BILL_CREDIT_TYPES = frozenset({WalletTxnType.REFUND})
SEPARATE_CHARGE_TYPES = frozenset(
    {WalletTxnType.ADDITIONAL_CHARGE, WalletTxnType.CHARGE_REVERSAL}
)
LEDGER_CREDIT_TYPES = frozenset(
    {WalletTxnType.RECHARGE, WalletTxnType.REFUND, WalletTxnType.COD_SETTLEMENT}
)

FULL_REFUND_STATUSES = {PickupStatus.CANCELLED, PickupStatus.LOST}

B2C_DROP_PINCODE = "110001"
STD_BOX_CM = (20.0, 15.0, 10.0)
TIME_SLOT = "10:00 - 14:00"

def expected_taxable(total: Decimal) -> Decimal:
    return M(total / Decimal("1.18"))

async def get_tenant_id():
    slug = resolve_golden_slug()
    async with GoldenSessionLocal() as session:
        t = await session.exec(select(Tenant).where(Tenant.slug == slug))
        return t.one().id

# ... test cases ...


def _client() -> httpx.AsyncClient:
    """In-process HTTP client (Spring: MockMvc)."""
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _box(
    dims: Tuple[float, float, float], weight: float, count: int = 1, **extra: Any
) -> Dict[str, Any]:
    """One package row (booking / PATCH / measurement shape)."""
    length, breadth, height = dims
    row: Dict[str, Any] = {
        "length": length,
        "breadth": breadth,
        "height": height,
        "dimension_unit": "CM",
        "weight": weight,
        "weight_unit": "KG",
        "box_count": count,
        "description": "Golden J-suite 9 carton",
    }
    row.update(extra)
    return row


def _drop_address(
    pincode: str = B2C_DROP_PINCODE, line1: str = "B-12, Connaught Place"
) -> Dict[str, Any]:
    """Consignee address snapshot (same pincode keeps the lane serviceable)."""
    city, state = (
        ("New Delhi", "Delhi")
        if pincode.startswith("11")
        else ("Mumbai", "Maharashtra")
    )
    return {
        "name": "Golden Consignee",
        "phone": "9810019901",
        "address_line1": line1,
        "city": city,
        "state": state,
        "pincode": pincode,
        "country": "IN",
        "category": "HOME",
    }


def _payment(
    mode: FreightPaymentMode = FreightPaymentMode.PREPAID,
    *,
    goods: float = 1000.0,
    is_cod: bool = False,
    add_shipping_to_cod: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Booking payment block; COD amount = goods value when COD is on."""
    block: Dict[str, Any] = {
        "freight_payment_mode": mode.value,
        "is_cod": is_cod,
        "cod_amount": goods if is_cod else 0.0,
        "shipment_value": goods,
        "shipment_tax_value": 0.0,
        "shipment_total_value": goods,
        "add_shipping_to_cod": add_shipping_to_cod,
    }
    block.update(extra)
    return block


async def _b2c_warehouse(client: httpx.AsyncClient, accounts: Mapping[str, Any]) -> str:
    """Seeded 122001 warehouse of customerb2c (Haryana: intra-state GST)."""
    return await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)


async def _b2b_dock(client: httpx.AsyncClient, accounts: Mapping[str, Any]) -> str:
    """Seeded 122001 dock of customerb2b."""
    return await find_seeded_address_id(client, accounts, CUSTOMER_B2B_EMAIL)


async def _book(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    email: str,
    *,
    label: str,
    pickup_address_id: str,
    packages: Sequence[Dict[str, Any]],
    payment: Dict[str, Any],
    service_type: ServiceType = ServiceType.SURFACE_ROAD,
    product_category: str = "ELECTRONICS",
    drop_pincode: str = B2C_DROP_PINCODE,
    **extra: Any,
) -> Dict[str, Any]:
    """Books one FORWARD shipment and returns the created PickupRead JSON (asserts 201)."""
    body: Dict[str, Any] = {
        "order_reference_id": order_ref(label),
        "shipment_type": "FORWARD",
        "service_type": service_type.value,
        "requested_pickup_date": date.today().isoformat(),
        "product_category": product_category,
        "pickup_address_id": pickup_address_id,
        "new_delivery_address": _drop_address(drop_pincode),
        "packages": list(packages),
        "payment_details": payment,
    }
    body.update(extra)
    if payment.get("freight_payment_mode") == FreightPaymentMode.TO_PAY.value:
        with allow_to_pay_bookings():
            resp = await client.post(
                "/api/v1/shipments", headers=headers(accounts, email), json=body
            )
    else:
        resp = await client.post(
            "/api/v1/shipments", headers=headers(accounts, email), json=body
        )
    assert resp.status_code == 201, resp.text
    
    shipment = resp.json()
    patch_resp = await client.patch(
        f"/api/v1/shipments/{shipment['id']}",
        headers=headers(accounts, ADMIN_EMAIL),
        json={"status": "OPEN", "comment": "Ready to ship"}
    )
    assert patch_resp.status_code == 200, patch_resp.text
    return patch_resp.json()


async def _book_b2c_2kg(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    label: str,
    *,
    mode: FreightPaymentMode = FreightPaymentMode.PREPAID,
    email: str = CUSTOMER_B2C_EMAIL,
    weight: float = 2.0,
    **payment_extra: Any,
) -> Dict[str, Any]:
    """The workhorse parcel: 20x15x10 cm, 2 kg, surface, Gurugram -> New Delhi."""
    print("_book_b2c_2kg: calling _b2c_warehouse")
    warehouse_id = await _b2c_warehouse(client, accounts)
    print("_book_b2c_2kg: calling _book")
    return await _book(
        client,
        accounts,
        email,
        label=label,
        pickup_address_id=warehouse_id,
        packages=[_box(STD_BOX_CM, weight)],
        payment=_payment(mode, **payment_extra),
    )


async def _get(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str = ADMIN_EMAIL,
) -> Dict[str, Any]:
    """GET /shipments/{id} (asserts 200)."""
    resp = await client.get(
        f"/api/v1/shipments/{sid}", headers=headers(accounts, email)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _patch(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str,
    body: Dict[str, Any],
) -> httpx.Response:
    """PATCH /shipments/{id} (status not asserted)."""
    return await client.patch(
        f"/api/v1/shipments/{sid}", headers=headers(accounts, email), json=body
    )


async def _preview(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /shipments/{id}/reprice-preview (asserts 200; preview never writes)."""
    resp = await client.post(
        f"/api/v1/shipments/{sid}/reprice-preview",
        headers=headers(accounts, email),
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _measure(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    *,
    packages: Optional[Sequence[Dict[str, Any]]] = None,
    weight_kg: Optional[float] = None,
    source: str = "HUB",
    email: str = OPERATIONS_EMAIL,
    idempotency_key: Optional[str] = None,
    remark: Optional[str] = None,
) -> httpx.Response:
    """POST /shipments/{id}/measurements: exactly one of packages / weight_kg."""
    body: Dict[str, Any] = {"source": source}
    if packages is not None:
        body["packages"] = list(packages)
    if weight_kg is not None:
        body["weight_kg"] = weight_kg
    if remark is not None:
        body["remark"] = remark
    hdrs = headers(accounts, email)
    if idempotency_key is not None:
        hdrs["Idempotency-Key"] = idempotency_key
    return await client.post(
        f"/api/v1/shipments/{sid}/measurements", headers=hdrs, json=body
    )


async def _charges(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str = ADMIN_EMAIL,
) -> List[Dict[str, Any]]:
    """GET /shipments/{id}/charges, oldest first (asserts 200)."""
    resp = await client.get(
        f"/api/v1/shipments/{sid}/charges", headers=headers(accounts, email)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _dispatch(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    merchant_email: str,
    pickup_address_id: str,
    shipment_ids: Sequence[str],
    *,
    service_flow: str = "B2C",
    measurements: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Creates a Pickup Request for the shipments and dispatches it (all picked) as ops."""
    pur = await client.post(
        "/api/v1/manifests",
        headers=headers(accounts, merchant_email),
        json={
            "pickup_address_id": pickup_address_id,
            "scheduled_date": date.today().isoformat(),
            "time_slot": TIME_SLOT,
            "service_flow": service_flow,
            "is_blind_pickup": False,
            "shipment_ids": list(shipment_ids),
        },
    )
    assert pur.status_code == 201, pur.text
    body: Dict[str, Any] = {"picked_shipment_ids": list(shipment_ids)}
    if measurements is not None:
        body["measurements"] = list(measurements)
    disp = await client.post(
        f"/api/v1/manifests/{pur.json()['id']}/dispatch",
        headers=headers(accounts, OPERATIONS_EMAIL),
        json=body,
    )
    assert disp.status_code == 200, disp.text
    return disp.json()


async def _book_and_dispatch_b2c_2kg(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    label: str,
    *,
    mode: FreightPaymentMode = FreightPaymentMode.PREPAID,
    **payment_extra: Any,
) -> Dict[str, Any]:
    """Books the 2 kg workhorse parcel and moves it to IN_TRANSIT through a B2C PUR."""
    booked = await _book_b2c_2kg(client, accounts, label, mode=mode, **payment_extra)
    warehouse_id = await _b2c_warehouse(client, accounts)
    await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [booked["id"]])
    shipment = await _get(client, accounts, booked["id"])
    assert shipment["status"] == PickupStatus.IN_TRANSIT.value
    return shipment


async def _raise_exception(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    reason: NdrExceptionReason,
    **extra: Any,
) -> Dict[str, Any]:
    """Ops raises an NDR / shipment exception (PATCH status=EXCEPTION)."""
    body: Dict[str, Any] = {
        "status": PickupStatus.EXCEPTION.value,
        "ndr_reason": reason.value,
        "ndr_remark": f"Golden J-suite 9: {reason.value}",
    }
    body.update(extra)
    resp = await _patch(client, accounts, sid, OPERATIONS_EMAIL, body)
    assert resp.status_code == 200, resp.text
    status = resp.json()["status"]
    assert status in {PickupStatus.EXCEPTION.value, PickupStatus.RTO_INITIATED.value, PickupStatus.CANCELLED.value}, f"Unexpected status: {status}"
    return resp.json()


async def _action(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /exceptions/{id}/actions (asserts 200)."""
    resp = await client.post(
        f"/api/v1/exceptions/{sid}/actions", headers=headers(accounts, email), json=body
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _std_package_patch(
    shipment: Mapping[str, Any], weight: float
) -> List[Dict[str, Any]]:
    """Full package rows for a PATCH that only changes the weight of the single box."""
    pkg = shipment["packages"][0]
    return [
        _box(
            (float(pkg["length"]), float(pkg["breadth"]), float(pkg["height"])),
            weight,
            int(pkg["box_count"]),
            id=pkg["id"],
        )
    ]


# --- DB oracle ---------------------------------------------------------------


@dataclass
class MoneySnapshot:
    """Everything money-related for one shipment, read straight from PostgreSQL."""

    shipment: PickupRequest
    payment: PaymentDetails
    txns: List[WalletTransaction]
    notes: List[BillingInvoice]
    adjustments: List[Any]
    measurements: List[Any]

    @property
    def total(self) -> Decimal:
        return M(self.payment.total_logistics_cost)

    @property
    def channel(self) -> Optional[str]:
        return (self.payment.pricing_breakdown or {}).get(BILLING_CHANNEL_KEY)

    def txns_of(self, *types: WalletTxnType) -> List[WalletTransaction]:
        wanted = {t.value for t in types}
        return [t for t in self.txns if _txn_type(t) in wanted]

    def notes_of(self, note_type: InvoiceNoteType) -> List[BillingInvoice]:
        return [n for n in self.notes if enum_value(n.note_type) == note_type.value]

    @property
    def active_measurement(self) -> Optional[Any]:
        active = [m for m in self.measurements if m.is_active]
        assert len(active) <= 1, "partial unique index: at most one active measurement"
        return active[0] if active else None


def enum_value(raw: Any) -> str:
    """Enum member or plain DB string -> its string value (never `str(member)`)."""
    return raw.value if hasattr(raw, "value") else str(raw)


def _txn_type(txn: WalletTransaction) -> str:
    """Enum-or-str txn type as its string value."""
    return enum_value(txn.txn_type)


def _is_completed(txn: WalletTransaction) -> bool:
    return enum_value(txn.status) == WalletTxnStatus.COMPLETED.value


def _note_belongs_to(note: BillingInvoice, sid: str) -> bool:
    """A GST document belongs to a shipment by column (M-B4) or by its line item."""
    if getattr(note, "shipment_id", None) is not None and str(note.shipment_id) == sid:
        return True
    return any(
        isinstance(item, dict) and item.get("shipment_id") == sid
        for item in (note.line_items or [])
    )


async def snapshot(sid: str) -> MoneySnapshot:
    tenant_id = await get_tenant_id()
    shipment_uuid = uuid.UUID(sid)

    async with GoldenSessionLocal() as session:
        shipment = (
            await session.exec(
                select(PickupRequest).where(
                    PickupRequest.id == shipment_uuid,
                    PickupRequest.tenant_id == tenant_id,
                )
            )
        ).first()
        assert shipment is not None, f"shipment {sid} not in the test tenant"
        payment = (
            await session.exec(
                select(PaymentDetails).where(PaymentDetails.pickup_id == shipment_uuid)
            )
        ).first()
        assert payment is not None
        txns = list(
            (
                await session.exec(
                    select(WalletTransaction)
                    .where(
                        WalletTransaction.tenant_id == tenant_id,
                        WalletTransaction.shipment_id == shipment_uuid,
                    )
                    .order_by(col(WalletTransaction.created_at))
                )
            ).all()
        )
        merchant_notes = list(
            (
                await session.exec(
                    select(BillingInvoice)
                    .where(
                        BillingInvoice.tenant_id == tenant_id,
                        BillingInvoice.merchant_user_id == shipment.created_by_user_id,
                        BillingInvoice.shipment_id == shipment_uuid,
                    )
                    .order_by(col(BillingInvoice.created_at))
                )
            ).all()
        )
        adjustments = list(
            (
                await session.exec(
                    select(ShipmentChargeAdjustment)
                    .where(
                        ShipmentChargeAdjustment.tenant_id == tenant_id,
                        ShipmentChargeAdjustment.pickup_id == shipment_uuid,
                    )
                    .order_by(col(ShipmentChargeAdjustment.created_at))
                )
            ).all()
        )
        measurements = list(
            (
                await session.exec(
                    select(ShipmentMeasurement)
                    .where(
                        ShipmentMeasurement.tenant_id == tenant_id,
                        ShipmentMeasurement.pickup_id == shipment_uuid,
                    )
                    .order_by(col(ShipmentMeasurement.measured_at))
                )
            ).all()
        )

        return MoneySnapshot(
            shipment=shipment,
            payment=payment,
            txns=txns,
            notes=merchant_notes,
            adjustments=adjustments,
            measurements=measurements,
        )


@dataclass
class StepDelta:
    """Rows created by one action (after minus before)."""

    txns: List[WalletTransaction]
    notes: List[BillingInvoice]
    adjustments: List[Any]
    measurements: List[Any]


def new_rows(before: MoneySnapshot, after: MoneySnapshot) -> StepDelta:
    """Returns the wallet txns, notes, adjustments and measurements created between two snapshots."""

    def _fresh(old: Iterable[Any], new: Iterable[Any]) -> List[Any]:
        seen = {row.id for row in old}
        return [row for row in new if row.id not in seen]

    return StepDelta(
        txns=_fresh(before.txns, after.txns),
        notes=_fresh(before.notes, after.notes),
        adjustments=_fresh(before.adjustments, after.adjustments),
        measurements=_fresh(before.measurements, after.measurements),
    )


def _sum(txns: Iterable[WalletTransaction], types: Iterable[WalletTxnType]) -> Decimal:
    wanted = {t.value for t in types}
    return sum(
        (M(t.amount) for t in txns if _is_completed(t) and _txn_type(t) in wanted),
        Decimal("0.00"),
    )


def is_wallet_billed(snap: MoneySnapshot) -> bool:
    """Plan B2: the billing_channel flag; legacy rows without it are wallet-billed iff PREPAID."""
    if snap.channel is not None:
        return snap.channel == CHANNEL_WALLET
    return snap.payment.freight_payment_mode == FreightPaymentMode.PREPAID


async def assert_wallet_matches_ledger(user_id: str) -> None:
    """Wallet balance == signed sum of its COMPLETED ledger, and every row's own math holds."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        wallet = (
            await session.exec(
                select(UserWallet).where(
                    UserWallet.user_id == uuid.UUID(user_id),
                    UserWallet.tenant_id == tenant_id,
                )
            )
        ).first()
        assert wallet is not None, f"no wallet for {user_id}"
        txns = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.tenant_id == tenant_id,
                )
            )
        ).all()
        await session.rollback()
    ledger = Decimal("0.00")
    for txn in txns:
        if not _is_completed(txn):
            continue
        signed = (
            M(txn.amount)
            if _txn_type(txn) in {t.value for t in LEDGER_CREDIT_TYPES}
            else -M(txn.amount)
        )
        assert (
            M(txn.closing_balance) == M(txn.opening_balance) + signed
        ), f"txn {txn.receipt_number}: closing != opening + signed amount"
        ledger += signed
    assert (
        M(wallet.balance) == ledger
    ), f"wallet {M(wallet.balance)} != ledger sum {ledger}"


async def assert_money_invariants(
    sid: str, user_id: Optional[str] = None
) -> MoneySnapshot:
    """
    The three Phase B money invariants for one shipment, straight from the DB:
    refunds <= debits (H-1); bill notes == net debited (and == bill when wallet-billed);
    merchant wallet == ledger sum.
    """
    snap = await snapshot(sid)
    debits = _sum(snap.txns, BILL_DEBIT_TYPES)
    refunds = _sum(snap.txns, BILL_CREDIT_TYPES)
    assert refunds <= debits, f"H-1: refunds {refunds} exceed bill debits {debits}"
    net = debits - refunds
    separate = _sum(snap.txns, SEPARATE_CHARGE_TYPES)
    invoices = sum(
        (M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.INVOICE)),
        Decimal("0.00"),
    )
    debit_notes = sum(
        (M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.DEBIT_NOTE)),
        Decimal("0.00"),
    )
    credit_notes = sum(
        (M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.CREDIT_NOTE)),
        Decimal("0.00"),
    )
    bill_notes = invoices + debit_notes - credit_notes - separate
    assert bill_notes == net, (
        f"GST register {bill_notes} (INVOICE {invoices} + DN {debit_notes} - CN {credit_notes} "
        f"- separate {separate}) != net debited {net}"
    )
    assert (
        len(snap.notes_of(InvoiceNoteType.INVOICE)) <= 1
    ), "at most one INVOICE per shipment"
    if is_wallet_billed(snap):
        fully_refunded = snap.shipment.status in FULL_REFUND_STATUSES
        expected_net = Decimal("0.00") if fully_refunded else snap.total
        assert (
            net == expected_net
        ), f"wallet-billed: net debited {net} != bill {expected_net}"
    for adj in snap.adjustments:
        assert M(adj.delta) == M(adj.new_total) - M(adj.old_total)
    await assert_wallet_matches_ledger(user_id or str(snap.shipment.created_by_user_id))
    return snap


async def next_document_number(note_type: InvoiceNoteType) -> str:
    """The exact next GST number of the test tenant's series (max serial + 1)."""
    prefix = document_prefix(note_type.value)
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        numbers = (
            await session.exec(
                select(BillingInvoice.invoice_number).where(
                    BillingInvoice.tenant_id == tenant_id,
                    col(BillingInvoice.invoice_number).startswith(prefix),
                )
            )
        ).all()
        await session.rollback()
    serials = [int(n[len(prefix) :]) for n in numbers if n[len(prefix) :].isdigit()]
    return format_document_number(prefix, (max(serials) if serials else 0) + 1)


def assert_gst_note(
    note: BillingInvoice,
    *,
    note_type: InvoiceNoteType,
    amount: Decimal,
    number: Optional[str] = None,
    original_invoice: Optional[BillingInvoice] = None,
    shipment_id: Optional[str] = None,
) -> None:
    """One GST document: exact amount, 18 % back-calculation, CGST/SGST or IGST, Rule 53 link."""
    assert enum_value(note.note_type) == note_type.value
    assert (
        M(note.total_amount) == amount
    ), f"{note.invoice_number}: {M(note.total_amount)} != {amount}"
    taxable = expected_taxable(amount)
    assert M(note.freight_amount) == taxable
    cgst, sgst, igst = M(note.cgst_amount), M(note.sgst_amount), M(note.igst_amount)
    assert cgst + sgst + igst == amount - taxable
    if igst > 0:
        assert cgst == Decimal("0.00") and sgst == Decimal("0.00")
    else:
        assert abs(cgst - sgst) <= MAX_GST_SPLIT_SKEW
    assert len(note.invoice_number) <= MAX_DOCUMENT_NUMBER_LENGTH
    assert note.invoice_number.startswith(document_prefix(note_type.value))
    if number is not None:
        assert (
            note.invoice_number == number
        ), f"{note.invoice_number} != expected {number}"
    if original_invoice is not None:
        assert (
            note.original_invoice_id == original_invoice.id
        ), "CGST Rule 53: note must quote its invoice"
    if shipment_id is not None:
        assert str(note.shipment_id) == shipment_id


def only(rows: Sequence[Any], what: str) -> Any:
    """Exactly one row."""
    assert len(rows) == 1, f"expected exactly one {what}, got {len(rows)}"
    return rows[0]


def assert_adjustment(
    adj: Any, *, reasons: Iterable[ChargeAdjustmentReason], old: Decimal, new: Decimal
) -> None:
    """One audit-trail row: reason, old/new totals and delta (DB CHECK: delta = new - old)."""
    allowed = {r.value for r in reasons}
    assert (
        enum_value(adj.reason) in allowed
    ), f"adjustment reason {adj.reason} not in {sorted(allowed)}"
    assert M(adj.old_total) == old
    assert M(adj.new_total) == new
    assert M(adj.delta) == new - old


async def assert_wallet_step(
    user_id: str, before_balance: float, expected_wallet_delta: Decimal
) -> None:
    """Merchant wallet moved by exactly `expected_wallet_delta` (negative = debit)."""
    after = await get_wallet_balance(user_id)
    assert (
        M(after) == M(before_balance) + expected_wallet_delta
    ), f"wallet {M(after)} != {M(before_balance)} + {expected_wallet_delta}"


async def test_j56_forward_out_for_delivery():
    """J56: forward with Out for delivery, then Delivered with the consignee OTP (H-11)."""
    accounts = await load_accounts()
    ops = headers(accounts, OPERATIONS_EMAIL)
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J21")
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

        resp = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=ops,
            json={"status": "OUT_FOR_DELIVERY", "comment": "Out for delivery"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "OUT_FOR_DELIVERY"

        otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2C_EMAIL, sid)
        resp = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=ops,
            json={
                "status": "COMPLETED",
                "comment": "Delivered",
                "delivery_otp": otp,
                "pod_received_by": "Golden Consignee",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "COMPLETED"


async def test_j57_3_ndrs_to_auto_rto():
    """J57: 3 NDRs -> auto-RTO, with RTO_FREIGHT + DN and a COD-fee CN"""
    accounts = await load_accounts()
    ops = headers(accounts, OPERATIONS_EMAIL)
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J22", is_cod=True)
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

        for i in range(3):
            # OFD
            await client.patch(
                f"/api/v1/shipments/{sid}",
                headers=ops,
                json={"status": "OUT_FOR_DELIVERY", "comment": "OFD"},
            )
            # NDR
            await _raise_exception(
                client, accounts, sid, NdrExceptionReason.CONSIGNEE_UNAVAILABLE
            )
            if i < 2:
                # Reattempt
                await _action(
                    client,
                    accounts,
                    sid,
                    CUSTOMER_B2C_EMAIL,
                    {"action": NdrAction.REATTEMPT.value},
                )

        # 3rd NDR should have triggered auto RTO
        snap = await assert_money_invariants(sid)
        assert enum_value(snap.shipment.status) == PickupStatus.RTO_INITIATED.value
        assert enum_value(snap.payment.cod_remittance_status) == CodRemittanceStatus.FAILED_RTO.value
        assert M((snap.payment.pricing_breakdown or {}).get("cod_fee", 0)) == Decimal("0.00")

        # C2 / D50: the COD fee is reversed with its own CN, then the RTO leg is billed
        # once as RTO_FREIGHT with its own DN; each note equals its adjustment's delta.
        cod_adj = only(
            [a for a in snap.adjustments if enum_value(a.reason) == ChargeAdjustmentReason.COD_FEE_REVERSAL.value],
            "COD_FEE_REVERSAL adjustment",
        )
        rto_adj = only(
            [a for a in snap.adjustments if enum_value(a.reason) == ChargeAdjustmentReason.RTO.value],
            "RTO adjustment",
        )
        assert M(cod_adj.delta) < Decimal("0.00") < M(rto_adj.delta)
        cn = only(snap.notes_of(InvoiceNoteType.CREDIT_NOTE), "CREDIT_NOTE")
        assert M(cn.total_amount) == -M(cod_adj.delta)
        rto_txn = only(snap.txns_of(WalletTxnType.RTO_FREIGHT), "RTO_FREIGHT txn")
        assert M(rto_txn.amount) == M(rto_adj.delta)
        assert M(rto_adj.delta) in {M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.DEBIT_NOTE)}
        assert snap.total == M(rto_adj.new_total)


async def _dashboard_stages(client: httpx.AsyncClient, accounts: Mapping[str, Any]) -> Dict[str, int]:
    """The merchant's B2C dashboard stage counters (`GET /api/v1/dashboard/summary`)."""
    resp = await client.get(
        "/api/v1/dashboard/summary?service_flow=B2C&days=30", headers=headers(accounts, CUSTOMER_B2C_EMAIL)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["stages"]


async def test_j58_rto_legs_to_rto_delivered():
    """J58: the RTO legs to RTO_DELIVERED, dashboard counts it as RTO, not Delivered"""
    accounts = await load_accounts()
    ops = headers(accounts, OPERATIONS_EMAIL)
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J23")
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

                # Cancel in transit to force RTO
        await client.post(
            f"/api/v1/shipments/{sid}/cancel",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        )

        snap = await snapshot(sid)
        assert enum_value(snap.shipment.status) == PickupStatus.RTO_INITIATED.value
        stages_before = await _dashboard_stages(client, accounts)

        # RTO_IN_TRANSIT
        await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=ops,
            json={"status": "RTO_IN_TRANSIT", "comment": "moving"},
        )

        # RTO_DELIVERED
        resp = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=ops,
            json={"status": "RTO_DELIVERED", "comment": "rto delivered"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "RTO_DELIVERED"

        # C5: the returned parcel stays counted as RTO and never becomes "Delivered".
        stages_after = await _dashboard_stages(client, accounts)
        assert stages_after["rto"] == stages_before["rto"] >= 1
        assert stages_after["delivered"] == stages_before["delivered"]


async def test_j59_refused_to_pay_merchant_billed():
    """J59: a refused TO_PAY parcel billed to the merchant"""
    accounts = await load_accounts()
    ops = headers(accounts, OPERATIONS_EMAIL)
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        booked = await _book_b2c_2kg(
            client, accounts, "J24", mode=FreightPaymentMode.TO_PAY
        )
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

        await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=ops,
            json={"status": "OUT_FOR_DELIVERY", "comment": "OFD"},
        )

        bal_before = await get_wallet_balance(merchant_id)

        # Refused -> RTO
        await _raise_exception(
            client, accounts, sid, NdrExceptionReason.CONSIGNEE_REFUSED
        )
        await _action(
            client,
            accounts,
            sid,
            CUSTOMER_B2C_EMAIL,
            {"action": NdrAction.RETURN_TO_ORIGIN.value},
        )

        snap = await assert_money_invariants(sid, merchant_id)
        assert enum_value(snap.shipment.status) == PickupStatus.RTO_INITIATED.value

        # C2: nobody pays at the door any more; the merchant is billed forward + RTO once,
        # as one RTO_FREIGHT debit with a GST INVOICE (a TO_PAY parcel had none before).
        assert M((snap.payment.pricing_breakdown or {}).get("rto_surcharge", 0)) > Decimal("0.00")
        rto_txn = only(snap.txns_of(WalletTxnType.RTO_FREIGHT), "RTO_FREIGHT txn")
        assert M(rto_txn.amount) == snap.total
        invoice = only(snap.notes_of(InvoiceNoteType.INVOICE), "merchant INVOICE")
        assert M(invoice.total_amount) == snap.total
        assert snap.notes_of(InvoiceNoteType.DEBIT_NOTE) == []
        assert M(snap.payment.freight_collectible) == Decimal("0.00")
        await assert_wallet_step(merchant_id, bal_before, -snap.total)


async def test_j60_customer_postpaid_rto_wallet():
    """J60: customer POSTPAID parcel's RTO billed through the wallet (RTO_FREIGHT + DN)"""
    accounts = await load_accounts()
    async with _client() as client:
        booked = await _book_b2c_2kg(
            client, accounts, "J25", mode=FreightPaymentMode.POSTPAID
        )
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

        await client.post(
            f"/api/v1/shipments/{sid}/cancel",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        )

        snap = await snapshot(sid)
        assert enum_value(snap.shipment.status) == PickupStatus.RTO_INITIATED.value

        rto_txns = [
            t
            for t in snap.txns
            if enum_value(t.txn_type) == WalletTxnType.RTO_FREIGHT.value
        ]
        assert len(rto_txns) == 1


async def test_j61_cancel_in_transit_rto():
    """J61: cancel in transit -> RTO"""
    accounts = await load_accounts()
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J26")
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

        resp = await client.post(
            f"/api/v1/shipments/{sid}/cancel",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "RTO_INITIATED"


async def test_j62_lost_refund():
    """J62: LOST refund (A-22: Owner/Admin marks LOST and found)."""
    accounts = await load_accounts()
    admin = headers(accounts, ADMIN_EMAIL)
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J27")
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

        bal_before = await get_wallet_balance(merchant_id)
        booked_snap = await snapshot(sid)
        resp = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=admin,
            json={"status": "LOST", "comment": "Lost"},
        )
        assert resp.status_code == 200, resp.text

        # C4: full refund of the net freight + a CN of exactly that amount, no RTO charge.
        snap = await assert_money_invariants(sid, merchant_id)
        assert enum_value(snap.shipment.status) == PickupStatus.LOST.value
        refund = only(new_rows(booked_snap, snap).txns, "refund txn")
        assert enum_value(refund.txn_type) == WalletTxnType.REFUND.value
        assert M(refund.amount) == booked_snap.total
        cn = only(new_rows(booked_snap, snap).notes, "credit note")
        assert enum_value(cn.note_type) == InvoiceNoteType.CREDIT_NOTE.value
        assert M(cn.total_amount) == booked_snap.total
        assert snap.txns_of(WalletTxnType.RTO_FREIGHT) == []
        await assert_wallet_step(merchant_id, bal_before, booked_snap.total)

        # C4: LOST is not terminal; a found parcel is billed again (SPEND + DN) and moves on.
        found_before = await get_wallet_balance(merchant_id)
        resp = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=admin,
            json={"status": "IN_TRANSIT", "comment": "Found at hub"},
        )
        assert resp.status_code == 200, resp.text
        found = await assert_money_invariants(sid, merchant_id)
        assert enum_value(found.shipment.status) == PickupStatus.IN_TRANSIT.value
        delta = new_rows(snap, found)
        rebill = only(delta.txns, "re-debit txn")
        assert enum_value(rebill.txn_type) == WalletTxnType.SPEND.value
        assert M(rebill.amount) == booked_snap.total
        dn = only(delta.notes, "debit note")
        assert enum_value(dn.note_type) == InvoiceNoteType.DEBIT_NOTE.value
        assert M(dn.total_amount) == booked_snap.total
        assert_adjustment(
            only(delta.adjustments, "LOST_FOUND adjustment"),
            reasons=[ChargeAdjustmentReason.LOST_FOUND],
            old=booked_snap.total,
            new=booked_snap.total,
        )
        await assert_wallet_step(merchant_id, found_before, -booked_snap.total)


async def test_j63_forbidden_jump_refused():
    """J63: every forbidden jump refused."""
    accounts = await load_accounts()
    ops = headers(accounts, OPERATIONS_EMAIL)
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J28")
        sid = booked["id"]
        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])

                # RTO_INITIATED to COMPLETED is forbidden (H-6)
        await client.post(
            f"/api/v1/shipments/{sid}/cancel",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        )

        resp = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=ops,
            json={"status": "COMPLETED", "comment": "should fail"},
        )
        assert resp.status_code == 400
