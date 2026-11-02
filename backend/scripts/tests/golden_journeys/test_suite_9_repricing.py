"""
Golden Test Suite 9 (`J37-J53`, `J46b`, race tests R1-R3): re-pricing on change.

Ship-readiness plan, Phase B (lean MVP rules, plan section 2.0). Every price change
after booking must:
- re-price through the one `RepricingService` (preview == saved total, H-7 Rs.0 guard);
- settle by billing channel: wallet-billed (PREPAID, customer POSTPAID) moves the
  wallet with a GST DEBIT_NOTE / CREDIT_NOTE for exactly the delta, never blocked by
  balance; TO_PAY moves `freight_collectible`; staff-booked POSTPAID is record-only;
- write one `shipment_charge_adjustments` row (the audit trail).

Every money assertion also checks PostgreSQL (`_assert_money_invariants`):
- refunds never exceed bill debits (H-1);
- INVOICE + DEBIT_NOTE - CREDIT_NOTE (bill notes) == net debited, and for a
  wallet-billed live shipment net debited == the bill (`total_logistics_cost`);
- the merchant wallet balance == its COMPLETED ledger sum, row by row.

Expected rupee values are hard-coded from the frozen `logismart-test` rate card
(base Rs.50/kg, fuel 10 %, network Rs.25, COD fee 2 %, RTO +50 % of base, B2B docket
Rs.50 + 10 kg floor, FOV 0.2 %, GST 18 %), so a drift in any code path fails loudly.
GST numbers are asserted exactly: the next serial of the tenant's `LTST` series.

Runs ONLY on the guarded test tenant (`golden_env`), reset once per session by
`golden_journeys/conftest.py`. Each journey books its own shipments, so the suite
also runs alone. Assertions on wallets are deltas (other suites share the wallets).

Spring analogy: one `@SpringBootTest` class per journey group, `MockMvc`
(`ASGITransport`) for HTTP, and a JPA repository read for the DB oracle.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import httpx
import pytest
from httpx import ASGITransport
from sqlmodel import col, select

from app.main import app
from app.models.delhivery_modules import (
    BillingInvoice,
    InvoiceNoteType,
    WeightDisputeClaimStatus,
)
from app.models.pickups import (
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
    MeasurementSource,
    ShipmentChargeAdjustment,
    ShipmentMeasurement,
)
from app.models.wallet import (
    UserWallet,
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
)
from app.schemas.v1.repricing import RejectionRule, SettlementAction
from app.services.delhivery_modules import format_document_number

from .golden_env import (
    GoldenSessionLocal,
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    OPERATIONS_EMAIL,
    OWNER_EMAIL,
    allow_to_pay_bookings,
    document_prefix,
    find_seeded_address_id,
    get_tenant_id,
    get_wallet_balance,
    headers,
    load_accounts,
    order_ref,
    read_otp_as_merchant,
)

# --- Money constants (plan section 2.0: "what the bill is") ------------------

MONEY_QUANT = Decimal("0.01")
GST_DIVISOR = Decimal("1.18")
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
"""Wallet debits that pay the bill (plan section 2.0)."""
BILL_CREDIT_TYPES = frozenset({WalletTxnType.REFUND})
SEPARATE_CHARGE_TYPES = frozenset(
    {WalletTxnType.ADDITIONAL_CHARGE, WalletTxnType.CHARGE_REVERSAL}
)
"""Own DEBIT_NOTE, outside the bill, never refunded by a cancellation."""
LEDGER_CREDIT_TYPES = frozenset(
    {WalletTxnType.RECHARGE, WalletTxnType.REFUND, WalletTxnType.COD_SETTLEMENT}
)
"""Signed-ledger credits; every other COMPLETED txn type is a debit."""

BILLING_CHANNEL_KEY = "billing_channel"
CHANNEL_WALLET = BillingChannel.WALLET.value
CHANNEL_NONE = BillingChannel.NONE.value

# --- Shipment fixtures --------------------------------------------------------

B2C_DROP_PINCODE = "110001"
B2B_DROP_PINCODE = "400001"
UNSERVICEABLE_PINCODE = "999999"
TIME_SLOT = "10:00 - 14:00"
STD_BOX_CM = (20.0, 15.0, 10.0)
B2B_BOX_CM = (50.0, 40.0, 40.0)
EWAY_BILL_NUMBER = "371234567890"

# --- Expected prices on the logismart-test rate card (DESIGN.md v4) -----------
# FakeDelhiveryApi (divisor 5000, 500g slab) + Prime fixture lane (Delhi NCR -> Mumbai)

P_2KG = Decimal("159.30")  # 20x15x10 cm, 2 kg, surface, prepaid
P_3_5KG = Decimal("256.65")
P_1KG = Decimal("94.40")
P_5KG = Decimal("354.00")
P_COD1000_2KG = Decimal("182.90")  # COD fee Rs.20 on goods Rs.1,000
P_AIR_3KG = Decimal("341.02")  # 20x20x20 cm, 3 kg, Express (AIR)
P_AIR_2KG = Decimal("237.18")
P_3BOX_30CM = Decimal("1100.35")  # 3 x 30 cm cube (27000/5000=5.4 kg/box) -> 16.5 kg slab
P_4BOX_30CM = Decimal("1457.30")  # 4 x 30 cm cube -> 22.0 kg slab
P_BLIND_FLOOR = Decimal("1699.20")  # Prime 50 kg floor (1200 * 1.20 * 1.18)
P_BLIND_40_CARTONS = Decimal("13433.12")  # Prime 40 x 60x40x40 cm, 15 kg -> 853.333 kg
P_OVERSIZED = Decimal("2755.30")  # 130x40x40 cm, 20 kg -> 208000/5000 = 42.0 kg slab
P_MEASURED_100CM_22KG = Decimal("2106.30")  # 100x40x40 cm, 22 kg -> 160000/5000 = 32.0 kg slab
P_MEASURED_100CM_22KG_RTO = Decimal("3050.30")  # 32.0 kg forward (2106.30) + RTO (800 * 1.18 = 944.00)
P_MEASURED_100CM_40KG_RTO = Decimal("3805.50")  # 40.0 kg forward (2625.50) + RTO (1000 * 1.18 = 1180.00)
P_1_5KG = Decimal("126.85")  # 25x20x15 cm, 1.5 kg, surface, prepaid (3 x 500g slabs)
P_COD5000_1_5KG = Decimal("244.85")  # 25x20x15 cm, 1.5 kg, COD Rs.5,000 (+Rs.118.00)
P_2KG_RTO = Decimal("218.30")  # forward 2 kg + RTO leg (also the 2 kg reverse)
P_3_5KG_RTO = Decimal("359.90")
P_COD2000_3_5KG = Decimal("303.85")
P_B2B_4BOX = Decimal("2407.20")  # Prime 4 x 50x40x40 cm, 25 kg -> 100 kg (1700 * 1.20 * 1.18)
P_B2B_4BOX_160KG = Decimal("3256.80")  # Prime 4 x 50x40x40 cm, 40 kg -> 160 kg (2300 * 1.20 * 1.18)
P_B2B_DLV_4BOX_COD10000 = Decimal("6755.50")  # B2B DELHIVERY_SURFACE 100 kg + COD Rs.10,000
P_B2B_DLV_4BOX_COD7500 = Decimal("6696.50")  # B2B DELHIVERY_SURFACE 100 kg + COD Rs.7,500

P_2KG_PLUS_WEIGHT_CHARGE = Decimal("218.30")  # Rs.159.30 + Rs.50 weight charge + 18 % GST

FULL_REFUND_STATUSES = frozenset(
    {PickupStatus.CANCELLED, PickupStatus.QC_FAILED, PickupStatus.REJECTED_AT_PICKUP}
)
"""refund_all() statuses: net debited returns to Rs.0 while the bill keeps its history value."""


# =============================================================================
# Helpers: money, HTTP and the DB oracle
# =============================================================================


def M(value: Any) -> Decimal:
    """Rounds any JSON / DB money value to the paisa, half-up (same rule as core/money.py)."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def expected_taxable(total: Decimal) -> Decimal:
    """Taxable value contained in a GST-inclusive amount at 18 %."""
    return (total / GST_DIVISOR).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


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


def _drop_address(pincode: str = B2C_DROP_PINCODE, line1: str = "B-12, Connaught Place") -> Dict[str, Any]:
    """Consignee address snapshot (same pincode keeps the lane serviceable)."""
    city, state = ("New Delhi", "Delhi") if pincode.startswith("11") else ("Mumbai", "Maharashtra")
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
            resp = await client.post("/api/v1/shipments", headers=headers(accounts, email), json=body)
    else:
        resp = await client.post("/api/v1/shipments", headers=headers(accounts, email), json=body)
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
    warehouse_id = await _b2c_warehouse(client, accounts)
    return await _book(
        client,
        accounts,
        email,
        label=label,
        pickup_address_id=warehouse_id,
        packages=[_box(STD_BOX_CM, weight)],
        payment=_payment(mode, **payment_extra),
    )


async def _get(client: httpx.AsyncClient, accounts: Mapping[str, Any], sid: str, email: str = ADMIN_EMAIL) -> Dict[str, Any]:
    """GET /shipments/{id} (asserts 200)."""
    resp = await client.get(f"/api/v1/shipments/{sid}", headers=headers(accounts, email))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _patch(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], sid: str, email: str, body: Dict[str, Any]
) -> httpx.Response:
    """PATCH /shipments/{id} (status not asserted)."""
    return await client.patch(f"/api/v1/shipments/{sid}", headers=headers(accounts, email), json=body)


async def _preview(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], sid: str, email: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    """POST /shipments/{id}/reprice-preview (asserts 200; preview never writes)."""
    resp = await client.post(
        f"/api/v1/shipments/{sid}/reprice-preview", headers=headers(accounts, email), json=body
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
    return await client.post(f"/api/v1/shipments/{sid}/measurements", headers=hdrs, json=body)


async def _charges(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], sid: str, email: str = ADMIN_EMAIL
) -> List[Dict[str, Any]]:
    """GET /shipments/{id}/charges, oldest first (asserts 200)."""
    resp = await client.get(f"/api/v1/shipments/{sid}/charges", headers=headers(accounts, email))
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
    assert resp.json()["status"] == PickupStatus.EXCEPTION.value
    return resp.json()


async def _action(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], sid: str, email: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    """POST /exceptions/{id}/actions (asserts 200)."""
    resp = await client.post(
        f"/api/v1/exceptions/{sid}/actions", headers=headers(accounts, email), json=body
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _std_package_patch(shipment: Mapping[str, Any], weight: float) -> List[Dict[str, Any]]:
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
        isinstance(item, dict) and item.get("shipment_id") == sid for item in (note.line_items or [])
    )


async def snapshot(sid: str) -> MoneySnapshot:
    """Reads shipment, payment, wallet txns, GST notes, adjustments and measurements."""
    tenant_id = await get_tenant_id()
    shipment_uuid = uuid.UUID(sid)
    async with GoldenSessionLocal() as session:
        shipment = (
            await session.exec(
                select(PickupRequest).where(
                    PickupRequest.id == shipment_uuid, PickupRequest.tenant_id == tenant_id
                )
            )
        ).first()
        assert shipment is not None, f"shipment {sid} not in the test tenant"
        payment = (
            await session.exec(select(PaymentDetails).where(PaymentDetails.pickup_id == shipment_uuid))
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
        merchant_notes = (
            await session.exec(
                select(BillingInvoice).where(
                    BillingInvoice.tenant_id == tenant_id,
                    BillingInvoice.merchant_user_id == shipment.created_by_user_id,
                )
            )
        ).all()
        notes = [n for n in merchant_notes if _note_belongs_to(n, sid)]
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
        await session.rollback()
    return MoneySnapshot(shipment, payment, txns, notes, adjustments, measurements)


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
        (M(t.amount) for t in txns if _is_completed(t) and _txn_type(t) in wanted), Decimal("0.00")
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
                    UserWallet.user_id == uuid.UUID(user_id), UserWallet.tenant_id == tenant_id
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
        signed = M(txn.amount) if _txn_type(txn) in {t.value for t in LEDGER_CREDIT_TYPES} else -M(txn.amount)
        assert M(txn.closing_balance) == M(txn.opening_balance) + signed, (
            f"txn {txn.receipt_number}: closing != opening + signed amount"
        )
        ledger += signed
    assert M(wallet.balance) == ledger, f"wallet {M(wallet.balance)} != ledger sum {ledger}"


async def assert_money_invariants(sid: str, user_id: Optional[str] = None) -> MoneySnapshot:
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
    invoices = sum((M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.INVOICE)), Decimal("0.00"))
    debit_notes = sum((M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.DEBIT_NOTE)), Decimal("0.00"))
    credit_notes = sum((M(n.total_amount) for n in snap.notes_of(InvoiceNoteType.CREDIT_NOTE)), Decimal("0.00"))
    bill_notes = invoices + debit_notes - credit_notes - separate
    assert bill_notes == net, (
        f"GST register {bill_notes} (INVOICE {invoices} + DN {debit_notes} - CN {credit_notes} "
        f"- separate {separate}) != net debited {net}"
    )
    assert len(snap.notes_of(InvoiceNoteType.INVOICE)) <= 1, "at most one INVOICE per shipment"
    if is_wallet_billed(snap):
        fully_refunded = snap.shipment.status in FULL_REFUND_STATUSES
        expected_net = Decimal("0.00") if fully_refunded else snap.total
        assert net == expected_net, f"wallet-billed: net debited {net} != bill {expected_net}"
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
    serials = [int(n[len(prefix):]) for n in numbers if n[len(prefix):].isdigit()]
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
    assert M(note.total_amount) == amount, f"{note.invoice_number}: {M(note.total_amount)} != {amount}"
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
        assert note.invoice_number == number, f"{note.invoice_number} != expected {number}"
    if original_invoice is not None:
        assert note.original_invoice_id == original_invoice.id, "CGST Rule 53: note must quote its invoice"
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
    assert enum_value(adj.reason) in allowed, f"adjustment reason {adj.reason} not in {sorted(allowed)}"
    assert M(adj.old_total) == old
    assert M(adj.new_total) == new
    assert M(adj.delta) == new - old


async def assert_wallet_step(
    user_id: str, before_balance: float, expected_wallet_delta: Decimal
) -> None:
    """Merchant wallet moved by exactly `expected_wallet_delta` (negative = debit)."""
    after = await get_wallet_balance(user_id)
    assert M(after) == M(before_balance) + expected_wallet_delta, (
        f"wallet {M(after)} != {M(before_balance)} + {expected_wallet_delta}"
    )


# =============================================================================
# J37-J39: edits that must or must not change the price
# =============================================================================


@pytest.mark.asyncio
async def test_j37_cod_add_shipping_no_op_edit_never_drifts():
    """
    J37 (R1). PREPAID COD Rs.1,000 + add_shipping_to_cod, 2 kg: bill Rs.182.90 and COD
    collectible Rs.1,182.90. An admin fixes only the address line, then re-sends the
    unchanged payment block (today's drift trigger: the COD fee was re-based on goods +
    old freight, Rs.182.90 -> Rs.187.22). Both saves leave the bill, the collectible,
    the wallet, the GST register and the charges history untouched.
    """
    accounts = await load_accounts()
    async with _client() as client:
        booked = await _book_b2c_2kg(
            client, accounts, "J37", is_cod=True, add_shipping_to_cod=True
        )
        sid = booked["id"]
        pd = booked["payment_details"]
        assert M(pd["total_logistics_cost"]) == P_COD1000_2KG
        assert M(pd["cod_amount"]) == Decimal("1182.90")
        assert M(pd.get("freight_collectible", 0)) == Decimal("0.00")
        before = await assert_money_invariants(sid)

        address_fix = await _patch(
            client,
            accounts,
            sid,
            ADMIN_EMAIL,
            {
                "comment": "J37 address line correction only",
                "new_delivery_address": _drop_address(line1="B-12A, Connaught Place, Gate 2"),
            },
        )
        assert address_fix.status_code == 200, address_fix.text
        same_payment = await _patch(
            client,
            accounts,
            sid,
            ADMIN_EMAIL,
            {
                "comment": "J37 resend the unchanged payment block",
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": True,
                    "cod_amount": 1182.90,
                    "add_shipping_to_cod": True,
                    "shipment_value": 1000.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 1000.0,
                },
            },
        )
        assert same_payment.status_code == 200, same_payment.text
        final = same_payment.json()
        assert M(final["payment_details"]["total_logistics_cost"]) == P_COD1000_2KG
        assert M(final["payment_details"]["cod_amount"]) == Decimal("1182.90")
        assert final["delivery_address"]["address_line1"] == "B-12A, Connaught Place, Gate 2"

        after = await assert_money_invariants(sid)
        delta = new_rows(before, after)
        assert delta.txns == [], "no wallet movement on a no-op edit"
        assert delta.notes == [], "no GST note on a no-op edit"
        assert delta.adjustments == [], "no adjustment row when nothing changed"
        assert await _charges(client, accounts, sid) == []


@pytest.mark.asyncio
async def test_j38_admin_edit_up_then_down_issues_exact_debit_and_credit_notes():
    """
    J38 (R3, R30). PREPAID 2 kg Rs.159.30. Admin edits the weight to 3.5 kg
    (Rs.256.65: SPEND Rs.97.35 + DEBIT_NOTE Rs.97.35, taxable Rs.82.50), then to 1 kg
    (Rs.94.40: REFUND Rs.162.25 + CREDIT_NOTE Rs.162.25). Both notes quote the
    booking INVOICE (Rule 53), carry the next serial of their series, and the GST
    register INVOICE 159.30 + DN 97.35 - CN 162.25 == bill 94.40 == net debited.
    Each edit writes one ADMIN_EDIT adjustment linked to its txn and note, shown in
    GET /charges and in the activity diff.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J38")
        sid = booked["id"]
        assert M(booked["payment_details"]["total_logistics_cost"]) == P_2KG
        snap0 = await assert_money_invariants(sid)
        invoice = only(snap0.notes_of(InvoiceNoteType.INVOICE), "booking INVOICE")
        assert M(invoice.total_amount) == P_2KG

        # Up: 2 kg -> 3.5 kg
        bal = await get_wallet_balance(merchant_id)
        expected_dn = await next_document_number(InvoiceNoteType.DEBIT_NOTE)
        up = await _patch(
            client, accounts, sid, ADMIN_EMAIL,
            {"comment": "J38 weight 3.5 kg", "packages": _std_package_patch(booked, 3.5)},
        )
        assert up.status_code == 200, up.text
        assert M(up.json()["payment_details"]["total_logistics_cost"]) == P_3_5KG
        assert M(up.json()["payment_details"]["chargeable_weight"]) == Decimal("3.50")
        await assert_wallet_step(merchant_id, bal, Decimal("-97.35"))
        snap1 = await assert_money_invariants(sid)
        step1 = new_rows(snap0, snap1)
        debit = only(step1.txns, "upward wallet txn")
        assert _txn_type(debit) == WalletTxnType.SPEND.value
        assert M(debit.amount) == Decimal("97.35")
        dn = only(step1.notes, "DEBIT_NOTE")
        assert_gst_note(
            dn, note_type=InvoiceNoteType.DEBIT_NOTE, amount=Decimal("97.35"),
            number=expected_dn, original_invoice=invoice, shipment_id=sid,
        )
        adj1 = only(step1.adjustments, "adjustment")
        assert_adjustment(adj1, reasons={ChargeAdjustmentReason.ADMIN_EDIT}, old=P_2KG, new=P_3_5KG)
        assert adj1.wallet_txn_id == debit.id
        assert adj1.billing_invoice_id == dn.id

        # Down: 3.5 kg -> 1 kg
        bal = await get_wallet_balance(merchant_id)
        expected_cn = await next_document_number(InvoiceNoteType.CREDIT_NOTE)
        down = await _patch(
            client, accounts, sid, ADMIN_EMAIL,
            {"comment": "J38 weight 1 kg", "packages": _std_package_patch(up.json(), 1.0)},
        )
        assert down.status_code == 200, down.text
        assert M(down.json()["payment_details"]["total_logistics_cost"]) == P_1KG
        await assert_wallet_step(merchant_id, bal, Decimal("162.25"))
        snap2 = await assert_money_invariants(sid)
        step2 = new_rows(snap1, snap2)
        refund = only(step2.txns, "refund")
        assert _txn_type(refund) == WalletTxnType.REFUND.value
        assert M(refund.amount) == Decimal("162.25")
        cn = only(step2.notes, "CREDIT_NOTE")
        assert_gst_note(
            cn, note_type=InvoiceNoteType.CREDIT_NOTE, amount=Decimal("162.25"),
            number=expected_cn, original_invoice=invoice, shipment_id=sid,
        )
        adj2 = only(step2.adjustments, "adjustment")
        assert_adjustment(adj2, reasons={ChargeAdjustmentReason.ADMIN_EDIT}, old=P_3_5KG, new=P_1KG)
        assert snap2.total == P_1KG
        assert M(invoice.total_amount) + M(dn.total_amount) - M(cn.total_amount) == P_1KG

        rows = await _charges(client, accounts, sid)
        assert [M(r["delta"]) for r in rows] == [Decimal("97.35"), Decimal("-162.25")]
        assert rows[0]["note_number"] == dn.invoice_number
        assert rows[1]["note_number"] == cn.invoice_number
        assert rows[0]["note_type"] == InvoiceNoteType.DEBIT_NOTE.value

        timeline = await client.get(
            f"/api/v1/shipments/{sid}/timeline", headers=headers(accounts, ADMIN_EMAIL)
        )
        assert timeline.status_code == 200, timeline.text
        repricing_diffs = [
            (a.get("diff") or {}).get("repricing")
            for a in timeline.json()
            if (a.get("diff") or {}).get("repricing")
        ]
        assert len(repricing_diffs) == 2, "every price change leaves a structured activity diff"
        assert {M(d["delta"]) for d in repricing_diffs} == {Decimal("97.35"), Decimal("-162.25")}


@pytest.mark.asyncio
async def test_j39_unserviceable_pincode_edit_is_refused_and_price_kept():
    """
    J39 (R2, H-7). Express (AIR) 20x20x20 cm, 3 kg: Rs.341.02. An admin moves the consignee to
    pincode 999999 (unserviceable on FakeDelhiveryApi). PATCH -> 400 and nothing changes
    (address, bill, wallet, notes, charges). The preview of the same change returns 200
    with an H-7 rejected field.
    """
    accounts = await load_accounts()
    async with _client() as client:
        warehouse_id = await _b2c_warehouse(client, accounts)
        booked = await _book(
            client, accounts, CUSTOMER_B2C_EMAIL, label="J39",
            pickup_address_id=warehouse_id,
            packages=[_box((20.0, 20.0, 20.0), 3.0)],
            payment=_payment(),
            service_type=ServiceType.AIR,
        )
        sid = booked["id"]
        assert M(booked["payment_details"]["total_logistics_cost"]) == P_AIR_3KG
        before = await assert_money_invariants(sid)
        change = {
            "comment": "J39 move consignee to an unserviceable pin",
            "new_delivery_address": _drop_address(UNSERVICEABLE_PINCODE),
        }

        preview = await _preview(client, accounts, sid, ADMIN_EMAIL, change)
        assert any(r.get("rule") == RejectionRule.ZERO_QUOTE.value for r in preview["rejected_fields"]), preview

        refused = await _patch(client, accounts, sid, ADMIN_EMAIL, change)
        assert refused.status_code == 400, refused.text
        current = await _get(client, accounts, sid)
        assert current["delivery_address"]["pincode"] == B2C_DROP_PINCODE
        assert M(current["payment_details"]["total_logistics_cost"]) == P_AIR_3KG
        after = await assert_money_invariants(sid)
        delta = new_rows(before, after)
        assert (delta.txns, delta.notes, delta.adjustments) == ([], [], [])


# =============================================================================
# J40-J44: measurements at pickup and at the hub
# =============================================================================


@pytest.mark.asyncio
async def test_j40_rider_records_more_boxes_at_pickup_and_bill_follows():
    """
    J40 (R10, B5). Booked 3 boxes 30 cm cube, 3.4 kg each: volumetric 16.2 kg (16.5 kg slab) ->
    Rs.1,100.35. The rider finds 4 boxes, 3.5 kg each (14 kg actual, 21.6 kg volumetric -> 22.0 kg slab)
    and records them in the dispatch payload. The bill becomes Rs.1,457.30: one
    WEIGHT_AUDIT_DEBIT Rs.356.95 + DEBIT_NOTE Rs.356.95 (taxable Rs.302.50), never
    blocked by the wallet balance; one active PICKUP measurement (4 boxes, 14 / 21.6 /
    22 kg); one PICKUP_MEASUREMENT adjustment. The declared boxes stay as booked.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        warehouse_id = await _b2c_warehouse(client, accounts)
        booked = await _book(
            client, accounts, CUSTOMER_B2C_EMAIL, label="J40",
            pickup_address_id=warehouse_id,
            packages=[_box((30.0, 30.0, 30.0), 3.4, 3)],
            payment=_payment(goods=4000.0),
        )
        sid = booked["id"]
        assert M(booked["payment_details"]["total_logistics_cost"]) == P_3BOX_30CM
        assert M(booked["payment_details"]["chargeable_weight"]) == Decimal("16.50")
        snap0 = await assert_money_invariants(sid)
        invoice = only(snap0.notes_of(InvoiceNoteType.INVOICE), "booking INVOICE")
        bal = await get_wallet_balance(merchant_id)
        expected_dn = await next_document_number(InvoiceNoteType.DEBIT_NOTE)

        await _dispatch(
            client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid],
            measurements=[{
                "shipment_id": sid,
                "packages": [_box((30.0, 30.0, 30.0), 3.5, 4)],
                "remark": "J40 rider found 4 cartons",
            }],
        )
        shipment = await _get(client, accounts, sid)
        assert shipment["status"] == PickupStatus.IN_TRANSIT.value
        assert M(shipment["payment_details"]["total_logistics_cost"]) == P_4BOX_30CM
        assert M(shipment["payment_details"]["chargeable_weight"]) == Decimal("22.00")
        assert [p["box_count"] for p in shipment["packages"]] == [3], "declared boxes unchanged"
        await assert_wallet_step(merchant_id, bal, Decimal("-356.95"))

        snap1 = await assert_money_invariants(sid)
        step = new_rows(snap0, snap1)
        debit = only(step.txns, "measurement debit")
        assert _txn_type(debit) == WalletTxnType.WEIGHT_AUDIT_DEBIT.value
        assert M(debit.amount) == Decimal("356.95")
        assert_gst_note(
            only(step.notes, "DEBIT_NOTE"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("356.95"), number=expected_dn, original_invoice=invoice, shipment_id=sid,
        )
        measurement = snap1.active_measurement
        assert measurement is not None and enum_value(measurement.source) == MeasurementSource.PICKUP.value
        assert measurement.total_boxes == 4
        assert M(measurement.actual_weight_kg) == Decimal("14.00")
        assert M(measurement.volumetric_weight_kg) == Decimal("21.60")
        assert M(measurement.chargeable_weight_kg) == Decimal("22.00")
        adj = only(step.adjustments, "adjustment")
        assert_adjustment(adj, reasons={ChargeAdjustmentReason.PICKUP_MEASUREMENT}, old=P_3BOX_30CM, new=P_4BOX_30CM)
        assert adj.wallet_txn_id == debit.id


@pytest.mark.asyncio
async def test_j41_blind_b2b_lr_billed_on_cartons_picked_and_pending_marker():
    """
    J41 (R11, B5). customerb2b books two blind LRs (40 cartons expected), each billed
    at the B2B Prime floor Rs.1,699.20 (50 kg floor). At dispatch ops measure LR-1:
    40 x 60x40x40 cm, 15 kg -> 853.333 kg chargeable -> Rs.13,433.12,
    WEIGHT_AUDIT_DEBIT Rs.11,733.92 + DEBIT_NOTE. LR-2 is dispatched without pieces
    (allowed: lenient MVP): it stays at the floor, gets no adjustment, and the integrity
    audit lists it as an unmeasured blind LR WARNING, not a discrepancy.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2B_EMAIL]["id"]
    async with _client() as client:
        dock_id = await _b2b_dock(client, accounts)
        lrs = []
        for label in ("J41-LR1", "J41-LR2"):
            lr = await _book(
                client, accounts, CUSTOMER_B2B_EMAIL, label=label,
                pickup_address_id=dock_id, packages=[],
                payment=_payment(goods=25000.0),
                product_category="COMMERCIAL", drop_pincode=B2B_DROP_PINCODE,
                is_blind_pickup=True, estimated_box_count=40,
            )
            assert M(lr["payment_details"]["total_logistics_cost"]) == P_BLIND_FLOOR
            lrs.append(lr)
        lr1, lr2 = lrs[0]["id"], lrs[1]["id"]
        snap1_0 = await assert_money_invariants(lr1)
        snap2_0 = await assert_money_invariants(lr2)
        invoice = only(snap1_0.notes_of(InvoiceNoteType.INVOICE), "LR-1 INVOICE")
        bal = await get_wallet_balance(merchant_id)
        expected_dn = await next_document_number(InvoiceNoteType.DEBIT_NOTE)

        await _dispatch(
            client, accounts, CUSTOMER_B2B_EMAIL, dock_id, [lr1, lr2], service_flow="B2B",
            measurements=[{
                "shipment_id": lr1,
                "packages": [_box((60.0, 40.0, 40.0), 15.0, 40)],
                "remark": "J41 truck loaded 40 cartons",
            }],
        )
        lr1_now = await _get(client, accounts, lr1)
        assert M(lr1_now["payment_details"]["total_logistics_cost"]) == P_BLIND_40_CARTONS
        assert M(lr1_now["payment_details"]["chargeable_weight"]) == Decimal("853.33")
        await assert_wallet_step(merchant_id, bal, Decimal("-11733.92"))
        snap1_1 = await assert_money_invariants(lr1)
        step = new_rows(snap1_0, snap1_1)
        debit = only(step.txns, "blind LR debit")
        assert _txn_type(debit) == WalletTxnType.WEIGHT_AUDIT_DEBIT.value
        assert M(debit.amount) == Decimal("11733.92")
        assert_gst_note(
            only(step.notes, "DEBIT_NOTE"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("11733.92"), number=expected_dn, original_invoice=invoice, shipment_id=lr1,
        )
        assert snap1_1.active_measurement.total_boxes == 40
        assert_adjustment(
            only(step.adjustments, "adjustment"), reasons={ChargeAdjustmentReason.PICKUP_MEASUREMENT},
            old=P_BLIND_FLOOR, new=P_BLIND_40_CARTONS,
        )

        lr2_now = await _get(client, accounts, lr2)
        assert lr2_now["status"] == PickupStatus.IN_TRANSIT.value
        assert M(lr2_now["payment_details"]["total_logistics_cost"]) == P_BLIND_FLOOR
        snap2_1 = await assert_money_invariants(lr2)
        assert new_rows(snap2_0, snap2_1).adjustments == []
        assert snap2_1.active_measurement is None

        audit = await client.get(
            "/api/v1/wallet/audit-integrity", headers=headers(accounts, OWNER_EMAIL)
        )
        assert audit.status_code == 200, audit.text
        body = audit.json()
        assert any(lrs[1]["tracking_id"] in str(w) for w in body.get("warnings") or []), body
        assert not any(lr2 in str(d) for d in body.get("discrepancies") or [])


@pytest.mark.asyncio
async def test_j42_hub_measurement_keeps_dims_bills_both_ways_and_keeps_rto():
    """
    J42 (R12, R13, R14, R32). Large booking 130x40x40 cm, 20 kg: 41.6 kg vol -> 42.0 kg slab
    -> Rs.2,755.30. After pickup:
    1) a weight-only hub entry of 22 kg keeps the declared size: still 42.0 kg
       -> no change, no wallet line, no note (a HUB measurement row and a zero-delta
       HUB_MEASUREMENT adjustment are still recorded);
    2) a full hub measurement 100x40x40 cm, 22 kg -> 32.0 kg slab
       -> Rs.2,106.30: B2C re-bills down at once, REFUND Rs.649.00 + CREDIT_NOTE;
    3) RTO is billed on the measured parcel: Rs.3,050.30, RTO_FREIGHT Rs.944.00 + DN;
    4) a later measurement (40 kg) keeps the RTO leg: Rs.3,805.50, WEIGHT_AUDIT_DEBIT
       Rs.755.20 + DN.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        warehouse_id = await _b2c_warehouse(client, accounts)
        booked = await _book(
            client, accounts, CUSTOMER_B2C_EMAIL, label="J42",
            pickup_address_id=warehouse_id,
            packages=[_box((130.0, 40.0, 40.0), 20.0)],
            payment=_payment(goods=9000.0),
        )
        sid = booked["id"]
        assert M(booked["payment_details"]["total_logistics_cost"]) == P_OVERSIZED
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])
        snap0 = await assert_money_invariants(sid)
        invoice = only(snap0.notes_of(InvoiceNoteType.INVOICE), "INVOICE")

        # 1) weight-only 22 kg: declared 130 cm kept -> no change
        weight_only = await _measure(client, accounts, sid, weight_kg=22.0)
        assert weight_only.status_code == 200, weight_only.text
        assert M(weight_only.json()["shipment"]["payment_details"]["total_logistics_cost"]) == P_OVERSIZED
        snap1 = await assert_money_invariants(sid)
        step1 = new_rows(snap0, snap1)
        assert (step1.txns, step1.notes) == ([], [])
        assert M(snap1.active_measurement.chargeable_weight_kg) == Decimal("42.00")
        zero = only(step1.adjustments, "zero-delta adjustment")
        assert_adjustment(zero, reasons={ChargeAdjustmentReason.HUB_MEASUREMENT}, old=P_OVERSIZED, new=P_OVERSIZED)
        assert zero.wallet_txn_id is None and zero.billing_invoice_id is None

        # 2) full measurement 100x40x40, 22 kg -> refund
        bal = await get_wallet_balance(merchant_id)
        expected_cn = await next_document_number(InvoiceNoteType.CREDIT_NOTE)
        full = await _measure(client, accounts, sid, packages=[_box((100.0, 40.0, 40.0), 22.0)])
        assert full.status_code == 200, full.text
        pd = full.json()["shipment"]["payment_details"]
        assert M(pd["total_logistics_cost"]) == P_MEASURED_100CM_22KG
        assert M(pd["chargeable_weight"]) == Decimal("32.00")
        await assert_wallet_step(merchant_id, bal, Decimal("649.00"))
        snap2 = await assert_money_invariants(sid)
        step2 = new_rows(snap1, snap2)
        assert _txn_type(only(step2.txns, "refund")) == WalletTxnType.REFUND.value
        assert_gst_note(
            only(step2.notes, "CREDIT_NOTE"), note_type=InvoiceNoteType.CREDIT_NOTE,
            amount=Decimal("649.00"), number=expected_cn, original_invoice=invoice, shipment_id=sid,
        )
        assert len([m for m in snap2.measurements if m.is_active]) == 1

        # 3) RTO billed on the measured parcel
        bal = await get_wallet_balance(merchant_id)
        rto = await _patch(
            client, accounts, sid, ADMIN_EMAIL,
            {"status": PickupStatus.RTO_INITIATED.value, "comment": "J42 consignee refused"},
        )
        assert rto.status_code == 200, rto.text
        assert M(rto.json()["payment_details"]["total_logistics_cost"]) == P_MEASURED_100CM_22KG_RTO
        assert rto.json()["payment_details"]["pricing_breakdown"]["rto_surcharge"] == 800.0
        await assert_wallet_step(merchant_id, bal, Decimal("-944.00"))
        snap3 = await assert_money_invariants(sid)
        step3 = new_rows(snap2, snap3)
        rto_txn = only(step3.txns, "RTO debit")
        assert _txn_type(rto_txn) == WalletTxnType.RTO_FREIGHT.value
        assert M(rto_txn.amount) == Decimal("944.00")
        assert_gst_note(
            only(step3.notes, "RTO DEBIT_NOTE"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("944.00"), original_invoice=invoice, shipment_id=sid,
        )

        # 4) measurement after RTO keeps the RTO leg
        bal = await get_wallet_balance(merchant_id)
        after_rto = await _measure(client, accounts, sid, packages=[_box((100.0, 40.0, 40.0), 40.0)])
        assert after_rto.status_code == 200, after_rto.text
        pd = after_rto.json()["shipment"]["payment_details"]
        assert M(pd["total_logistics_cost"]) == P_MEASURED_100CM_40KG_RTO
        assert pd["pricing_breakdown"]["rto_surcharge"] == 1000.0
        await assert_wallet_step(merchant_id, bal, Decimal("-755.20"))
        snap4 = await assert_money_invariants(sid)
        step4 = new_rows(snap3, snap4)
        debit4 = only(step4.txns, "post-RTO measurement debit")
        assert _txn_type(debit4) == WalletTxnType.WEIGHT_AUDIT_DEBIT.value
        assert M(debit4.amount) == Decimal("755.20")
        assert len(snap4.txns_of(WalletTxnType.RTO_FREIGHT)) == 1, "RTO billed once"


@pytest.mark.asyncio
async def test_j43_admin_edit_after_hub_measurement_never_reverts_it():
    """
    J43 (R4). 2 kg Rs.159.30, dispatched; hub measures 20x15x10 cm, 3.5 kg ->
    Rs.256.65 (WEIGHT_AUDIT_DEBIT Rs.97.35 + DN). Then an admin fixes the address
    line, and later edits the DECLARED weight back to 1 kg. The active measurement
    stays the billing basis: the bill stays Rs.256.65, with no refund and no note.
    """
    accounts = await load_accounts()
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "J43")
        sid = shipment["id"]
        snap0 = await assert_money_invariants(sid)
        measured = await _measure(client, accounts, sid, packages=[_box(STD_BOX_CM, 3.5)])
        assert measured.status_code == 200, measured.text
        snap1 = await assert_money_invariants(sid)
        assert snap1.total == P_3_5KG
        step1 = new_rows(snap0, snap1)
        assert M(only(step1.txns, "measurement debit").amount) == Decimal("97.35")

        address = await _patch(
            client, accounts, sid, ADMIN_EMAIL,
            {"comment": "J43 address fix", "new_delivery_address": _drop_address(line1="B-14, Connaught Place")},
        )
        assert address.status_code == 200, address.text
        declared = await _patch(
            client, accounts, sid, ADMIN_EMAIL,
            {"comment": "J43 declared weight back to 1 kg", "packages": _std_package_patch(shipment, 1.0)},
        )
        assert declared.status_code == 200, declared.text
        assert M(declared.json()["payment_details"]["total_logistics_cost"]) == P_3_5KG
        snap2 = await assert_money_invariants(sid)
        step2 = new_rows(snap1, snap2)
        assert step2.txns == [] and step2.notes == [], "a declared edit never undoes a measurement"
        assert snap2.active_measurement.id == snap1.active_measurement.id


@pytest.mark.asyncio
async def test_j44_two_hub_audits_then_claim_accepted_restores_bill_and_manual_weight_charge():
    """
    J44 (R16, R17).
    Part A: 2 kg Rs.159.30 dispatched. Hub weight-only 3.5 kg -> Rs.256.65 (+97.35),
    then 5 kg -> Rs.354.00 (+97.35); each is a WEIGHT_AUDIT_DEBIT + DN. The Weight
    Mismatch row shows the cumulative cost difference Rs.194.70. The merchant claims
    2,000 g; the admin accepts: the bill is re-priced back to 2 kg (Rs.159.30),
    REFUND Rs.194.70 + CREDIT_NOTE Rs.194.70, an active CLAIM measurement, one
    CLAIM_ACCEPTED adjustment.
    Part B: ops raise WEIGHT_DISCREPANCY with charge_amount Rs.50 (GST-exclusive,
    D55). The merchant accepts: bill +Rs.59.00 -> Rs.218.30 as WEIGHT_AUDIT_DEBIT +
    DN Rs.59.00 (taxable Rs.50.00), adjustment MANUAL_WEIGHT_CHARGE, net == bill.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "J44A")
        sid, awb = shipment["id"], shipment["tracking_id"]
        for weight, total in ((3.5, P_3_5KG), (5.0, P_5KG)):
            before = await snapshot(sid)
            resp = await _measure(client, accounts, sid, weight_kg=weight)
            assert resp.status_code == 200, resp.text
            after = await assert_money_invariants(sid)
            assert after.total == total
            step = new_rows(before, after)
            assert _txn_type(only(step.txns, "audit debit")) == WalletTxnType.WEIGHT_AUDIT_DEBIT.value
            assert M(only(step.notes, "audit DN").total_amount) == Decimal("97.35")

        disputes = await client.get(
            f"/api/v1/disputes/weight-mismatch?search={awb}", headers=headers(accounts, CUSTOMER_B2C_EMAIL)
        )
        assert disputes.status_code == 200, disputes.text
        dispute = only(disputes.json(), "weight dispute")
        assert M(dispute["cost_diff_inr"]) == Decimal("194.70"), "cost difference is cumulative"

        claim = await client.post(
            "/api/v1/disputes/weight-mismatch/claims",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"tracking_ids": [awb], "claimed_weight_g": 2000.0, "claim_remarks": "J44 parcel is 2 kg"},
        )
        assert claim.status_code == 200, claim.text
        before = await snapshot(sid)
        invoice = only(before.notes_of(InvoiceNoteType.INVOICE), "INVOICE")
        bal = await get_wallet_balance(merchant_id)
        expected_cn = await next_document_number(InvoiceNoteType.CREDIT_NOTE)
        accept = await client.patch(
            f"/api/v1/disputes/weight-mismatch/{dispute['id']}/resolve",
            headers=headers(accounts, ADMIN_EMAIL),
            json={"claim_status": WeightDisputeClaimStatus.ACCEPTED.value, "claim_remarks": "J44 verified 2 kg"},
        )
        assert accept.status_code == 200, accept.text
        await assert_wallet_step(merchant_id, bal, Decimal("194.70"))
        after = await assert_money_invariants(sid)
        assert after.total == P_2KG
        assert M(after.payment.chargeable_weight) == Decimal("2.00")
        step = new_rows(before, after)
        refund = only(step.txns, "claim refund")
        assert _txn_type(refund) == WalletTxnType.REFUND.value
        assert M(refund.amount) == Decimal("194.70")
        assert_gst_note(
            only(step.notes, "claim CREDIT_NOTE"), note_type=InvoiceNoteType.CREDIT_NOTE,
            amount=Decimal("194.70"), number=expected_cn, original_invoice=invoice, shipment_id=sid,
        )
        assert enum_value(after.active_measurement.source) == MeasurementSource.CLAIM.value
        assert_adjustment(only(step.adjustments, "claim adjustment"), reasons={ChargeAdjustmentReason.CLAIM_ACCEPTED}, old=P_5KG, new=P_2KG)

        # Part B: manual weight charge through ACCEPT_WEIGHT
        ship_b = await _book_and_dispatch_b2c_2kg(client, accounts, "J44B")
        sid_b = ship_b["id"]
        await _raise_exception(
            client, accounts, sid_b, NdrExceptionReason.WEIGHT_DISCREPANCY, charge_amount=50.0
        )
        before_b = await snapshot(sid_b)
        bal = await get_wallet_balance(merchant_id)
        row = await _action(
            client, accounts, sid_b, CUSTOMER_B2C_EMAIL, {"action": NdrAction.ACCEPT_WEIGHT.value}
        )
        assert row["status"] == PickupStatus.IN_TRANSIT.value
        await assert_wallet_step(merchant_id, bal, Decimal("-59.00"))
        after_b = await assert_money_invariants(sid_b)
        assert after_b.total == P_2KG_PLUS_WEIGHT_CHARGE
        step_b = new_rows(before_b, after_b)
        charge = only(step_b.txns, "manual weight charge")
        assert _txn_type(charge) == WalletTxnType.WEIGHT_AUDIT_DEBIT.value
        assert M(charge.amount) == Decimal("59.00")
        assert_gst_note(
            only(step_b.notes, "manual weight DN"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("59.00"), shipment_id=sid_b,
        )
        assert_adjustment(
            only(step_b.adjustments, "manual weight adjustment"),
            reasons={ChargeAdjustmentReason.MANUAL_WEIGHT_CHARGE}, old=P_2KG, new=P_2KG_PLUS_WEIGHT_CHARGE,
        )


# =============================================================================
# J45-J47: payment mode, TO_PAY and POSTPAID settlement
# =============================================================================


@pytest.mark.asyncio
async def test_j45_payment_dispute_reprices_cod_fee_and_keeps_to_pay_freight():
    """
    J45 (R18, R19).
    Part A: PREPAID, goods Rs.5,000, 25x20x15 cm 1.5 kg -> Rs.159.30. Payment
    Dispute -> COD: Rs.277.30 (COD fee Rs.100 + GST): SPEND Rs.118.00 + DN, COD
    Rs.5,000. Second dispute -> prepaid: Rs.159.30, REFUND Rs.118.00 + CN, COD 0.
    Part B: TO_PAY + COD Rs.1,000 (+ add_shipping): bill Rs.182.90, cod_amount = goods
    Rs.1,000, freight_collectible Rs.182.90, nothing on the wallet. Dispute -> no COD:
    bill Rs.159.30, cod_amount 0, freight still collectible Rs.159.30, no wallet line,
    no note, one PAYMENT_MODE_CHANGE adjustment with no wallet txn.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        warehouse_id = await _b2c_warehouse(client, accounts)
        booked = await _book(
            client, accounts, CUSTOMER_B2C_EMAIL, label="J45A",
            pickup_address_id=warehouse_id,
            packages=[_box((25.0, 20.0, 15.0), 1.5)],
            payment=_payment(goods=5000.0),
        )
        sid = booked["id"]
        assert M(booked["payment_details"]["total_logistics_cost"]) == P_1_5KG
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])
        invoice = only((await snapshot(sid)).notes_of(InvoiceNoteType.INVOICE), "INVOICE")

        for is_cod, total, wallet_delta, txn_type, note_type, cod in (
            (True, P_COD5000_1_5KG, Decimal("-118.00"), WalletTxnType.SPEND, InvoiceNoteType.DEBIT_NOTE, Decimal("5000.00")),
            (False, P_1_5KG, Decimal("118.00"), WalletTxnType.REFUND, InvoiceNoteType.CREDIT_NOTE, Decimal("0.00")),
        ):
            await _raise_exception(client, accounts, sid, NdrExceptionReason.PAYMENT_DISPUTE)
            before = await snapshot(sid)
            bal = await get_wallet_balance(merchant_id)
            expected_no = await next_document_number(note_type)
            row = await _action(
                client, accounts, sid, CUSTOMER_B2C_EMAIL,
                {"action": NdrAction.UPDATE_PAYMENT_MODE.value, "is_cod": is_cod},
            )
            assert row["status"] == PickupStatus.IN_TRANSIT.value
            assert M(row["cod_amount"]) == cod
            await assert_wallet_step(merchant_id, bal, wallet_delta)
            after = await assert_money_invariants(sid)
            assert after.total == total
            step = new_rows(before, after)
            assert _txn_type(only(step.txns, "dispute txn")) == txn_type.value
            assert_gst_note(
                only(step.notes, "dispute note"), note_type=note_type, amount=Decimal("118.00"),
                number=expected_no, original_invoice=invoice, shipment_id=sid,
            )
            assert_adjustment(
                only(step.adjustments, "dispute adjustment"), reasons={ChargeAdjustmentReason.PAYMENT_MODE_CHANGE},
                old=P_1_5KG if is_cod else P_COD5000_1_5KG, new=total,
            )

        # Part B: TO_PAY + COD -> no COD keeps the freight collectible
        to_pay = await _book(
            client, accounts, CUSTOMER_B2C_EMAIL, label="J45B",
            pickup_address_id=warehouse_id,
            packages=[_box(STD_BOX_CM, 2.0)],
            payment=_payment(FreightPaymentMode.TO_PAY, is_cod=True, add_shipping_to_cod=True),
        )
        tid = to_pay["id"]
        pd = to_pay["payment_details"]
        assert M(pd["total_logistics_cost"]) == P_COD1000_2KG
        assert M(pd["cod_amount"]) == Decimal("1000.00"), "TO_PAY: freight never sits inside cod_amount"
        assert M(pd["freight_collectible"]) == P_COD1000_2KG
        assert pd["pricing_breakdown"][BILLING_CHANNEL_KEY] == CHANNEL_NONE
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [tid])
        await _raise_exception(client, accounts, tid, NdrExceptionReason.PAYMENT_DISPUTE)
        before = await assert_money_invariants(tid)
        assert before.txns == [] and before.notes == []
        bal = await get_wallet_balance(merchant_id)
        await _action(
            client, accounts, tid, CUSTOMER_B2C_EMAIL,
            {"action": NdrAction.UPDATE_PAYMENT_MODE.value, "is_cod": False},
        )
        await assert_wallet_step(merchant_id, bal, Decimal("0.00"))
        after = await assert_money_invariants(tid)
        assert after.total == P_2KG
        assert after.payment.is_cod is False
        assert M(after.payment.cod_amount) == Decimal("0.00")
        assert M(after.payment.freight_collectible) == P_2KG
        step = new_rows(before, after)
        assert (step.txns, step.notes) == ([], [])
        adj = only(step.adjustments, "TO_PAY dispute adjustment")
        assert_adjustment(adj, reasons={ChargeAdjustmentReason.PAYMENT_MODE_CHANGE}, old=P_COD1000_2KG, new=P_2KG)
        assert adj.wallet_txn_id is None


@pytest.mark.asyncio
async def test_j46_to_pay_increase_moves_collectible_before_delivery_and_freezes_after():
    """
    J46 (R15, R20, H-9). TO_PAY 2 kg: bill Rs.159.30, nothing on the wallet,
    freight_collectible Rs.159.30. Hub measures 3.5 kg before delivery: bill
    Rs.256.65, collectible Rs.256.65, no wallet line, no note, one HUB_MEASUREMENT
    adjustment with no wallet txn. After delivery (OTP) the collectible is frozen: a
    later measurement never changes what the rider collected, and never touches the
    merchant wallet (either refused with 400, or recorded with the collectible kept).
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(
            client, accounts, "J46", mode=FreightPaymentMode.TO_PAY
        )
        sid = shipment["id"]
        assert M(shipment["payment_details"]["freight_collectible"]) == P_2KG
        before = await assert_money_invariants(sid)
        bal = await get_wallet_balance(merchant_id)
        resp = await _measure(client, accounts, sid, weight_kg=3.5)
        assert resp.status_code == 200, resp.text
        pd = resp.json()["shipment"]["payment_details"]
        assert M(pd["total_logistics_cost"]) == P_3_5KG
        assert M(pd["freight_collectible"]) == P_3_5KG
        await assert_wallet_step(merchant_id, bal, Decimal("0.00"))
        after = await assert_money_invariants(sid)
        step = new_rows(before, after)
        assert (step.txns, step.notes) == ([], [])
        adj = only(step.adjustments, "TO_PAY measurement adjustment")
        assert_adjustment(adj, reasons={ChargeAdjustmentReason.HUB_MEASUREMENT}, old=P_2KG, new=P_3_5KG)
        assert adj.wallet_txn_id is None

        otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2C_EMAIL, sid)
        delivered = await _patch(
            client, accounts, sid, OPERATIONS_EMAIL,
            {"status": PickupStatus.COMPLETED.value, "delivery_otp": otp, "pod_received_by": "J46 consignee"},
        )
        assert delivered.status_code == 200, delivered.text
        frozen_before = await snapshot(sid)
        bal = await get_wallet_balance(merchant_id)
        late = await _measure(client, accounts, sid, weight_kg=5.0)
        assert late.status_code in (200, 400), late.text
        await assert_wallet_step(merchant_id, bal, Decimal("0.00"))
        frozen_after = await assert_money_invariants(sid)
        assert M(frozen_after.payment.freight_collectible) == P_3_5KG, "H-9: collectible frozen"
        assert new_rows(frozen_before, frozen_after).txns == []


@pytest.mark.asyncio
async def test_j46b_freight_collection_on_to_pay_moves_freight_to_merchant_wallet():
    """
    J46b (B3, J65b basis). TO_PAY 2 kg: bill Rs.159.30, freight_collectible Rs.159.30.
    Ops raise FREIGHT_COLLECTION for the outstanding freight (Rs.159.30, GST-inclusive)
    and the merchant acknowledges it: wallet -Rs.159.30 as a FREIGHT_COLLECTION txn,
    DEBIT_NOTE Rs.159.30 (taxable Rs.135.00); the bill is unchanged; the rider no
    longer collects freight (collectible Rs.0.00); one FREIGHT_COLLECTION adjustment.
    Notes == net debited (Rs.159.30), so nothing is billed twice later (J65b).
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(
            client, accounts, "J46b", mode=FreightPaymentMode.TO_PAY
        )
        sid = shipment["id"]
        await _raise_exception(
            client, accounts, sid, NdrExceptionReason.FREIGHT_COLLECTION, charge_amount=159.30
        )
        before = await snapshot(sid)
        bal = await get_wallet_balance(merchant_id)
        # C-03: TO_PAY has no prior INVOICE; orphan DEBIT_NOTE is promoted to INVOICE (Rule 53)
        expected_inv = await next_document_number(InvoiceNoteType.INVOICE)
        row = await _action(
            client, accounts, sid, CUSTOMER_B2C_EMAIL, {"action": NdrAction.ACKNOWLEDGE_CHARGES.value}
        )
        assert row["status"] == PickupStatus.IN_TRANSIT.value
        await assert_wallet_step(merchant_id, bal, Decimal("-159.30"))
        after = await assert_money_invariants(sid)
        assert after.total == P_2KG, "TO_PAY: the bill is unchanged by Freight Collection"
        assert M(after.payment.freight_collectible) == Decimal("0.00")
        step = new_rows(before, after)
        fc = only(step.txns, "freight collection txn")
        assert _txn_type(fc) == WalletTxnType.FREIGHT_COLLECTION.value
        assert M(fc.amount) == P_2KG
        assert_gst_note(
            only(step.notes, "freight collection invoice"), note_type=InvoiceNoteType.INVOICE,
            amount=P_2KG, number=expected_inv, shipment_id=sid,
        )
        adj = only(step.adjustments, "freight collection adjustment")
        assert enum_value(adj.reason) == ChargeAdjustmentReason.FREIGHT_COLLECTION.value
        assert adj.wallet_txn_id == fc.id


@pytest.mark.asyncio
async def test_j47_customer_postpaid_edits_settle_through_wallet_and_staff_postpaid_is_record_only():
    """
    J47 (B16, lean rule D85-b).
    Part A: customerb2c self-books POSTPAID 2 kg: billing_channel WALLET, SPEND
    Rs.159.30 + INVOICE. The merchant edits the weight while Ready to ship: 3.5 kg ->
    SPEND Rs.97.35 + DN, then 1 kg -> REFUND Rs.162.25 + CN, each a CUSTOMER_EDIT
    adjustment, exactly like PREPAID.
    Part B: admin books POSTPAID (staff): billing_channel NONE, no wallet line, no
    INVOICE. An admin edit to 3.5 kg re-prices to Rs.256.65 and writes a record-only
    ADMIN_EDIT adjustment: no wallet txn, no note.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    admin_id = accounts[ADMIN_EMAIL]["id"]
    async with _client() as client:
        bal = await get_wallet_balance(merchant_id)
        booked = await _book_b2c_2kg(client, accounts, "J47A", mode=FreightPaymentMode.POSTPAID)
        sid = booked["id"]
        assert booked["payment_details"]["pricing_breakdown"][BILLING_CHANNEL_KEY] == CHANNEL_WALLET
        await assert_wallet_step(merchant_id, bal, -P_2KG)
        snap0 = await assert_money_invariants(sid)
        invoice = only(snap0.notes_of(InvoiceNoteType.INVOICE), "POSTPAID INVOICE")
        assert M(invoice.total_amount) == P_2KG
        assert _txn_type(only(snap0.txns, "booking spend")) == WalletTxnType.SPEND.value

        current = booked
        for weight, total, wallet_delta, txn_type, note_type in (
            (3.5, P_3_5KG, Decimal("-97.35"), WalletTxnType.SPEND, InvoiceNoteType.DEBIT_NOTE),
            (1.0, P_1KG, Decimal("162.25"), WalletTxnType.REFUND, InvoiceNoteType.CREDIT_NOTE),
        ):
            before = await snapshot(sid)
            bal = await get_wallet_balance(merchant_id)
            edit = await _patch(
                client, accounts, sid, CUSTOMER_B2C_EMAIL,
                {"comment": f"J47 merchant sets {weight} kg", "packages": _std_package_patch(current, weight)},
            )
            assert edit.status_code == 200, edit.text
            current = edit.json()
            assert M(current["payment_details"]["total_logistics_cost"]) == total
            await assert_wallet_step(merchant_id, bal, wallet_delta)
            after = await assert_money_invariants(sid)
            step = new_rows(before, after)
            assert _txn_type(only(step.txns, "edit txn")) == txn_type.value
            assert_gst_note(
                only(step.notes, "edit note"), note_type=note_type, amount=abs(wallet_delta),
                original_invoice=invoice, shipment_id=sid,
            )
            assert_adjustment(
                only(step.adjustments, "edit adjustment"), reasons={ChargeAdjustmentReason.CUSTOMER_EDIT},
                old=before.total, new=total,
            )

        # Part B: #558 (3a) staff-booked POSTPAID is also wallet-billed (no walk-in on-behalf in MVP)
        admin_bal = await get_wallet_balance(admin_id)
        staff = await _book_b2c_2kg(
            client, accounts, "J47B", mode=FreightPaymentMode.POSTPAID, email=ADMIN_EMAIL
        )
        stid = staff["id"]
        assert staff["payment_details"]["pricing_breakdown"][BILLING_CHANNEL_KEY] == CHANNEL_WALLET
        await assert_wallet_step(admin_id, admin_bal, -P_2KG)
        staff0 = await assert_money_invariants(stid)
        assert len(staff0.txns) == 1 and len(staff0.notes) == 1
        admin_bal_after_book = await get_wallet_balance(admin_id)
        edit = await _patch(
            client, accounts, stid, ADMIN_EMAIL,
            {"comment": "J47 staff POSTPAID weight 3.5 kg", "packages": _std_package_patch(staff, 3.5)},
        )
        assert edit.status_code == 200, edit.text
        assert M(edit.json()["payment_details"]["total_logistics_cost"]) == P_3_5KG
        await assert_wallet_step(admin_id, admin_bal_after_book, -(P_3_5KG - P_2KG))
        staff1 = await assert_money_invariants(stid)
        step = new_rows(staff0, staff1)
        assert len(step.txns) == 1 and len(step.notes) == 1
        adj = only(step.adjustments, "staff postpaid adjustment")
        assert_adjustment(adj, reasons={ChargeAdjustmentReason.ADMIN_EDIT}, old=P_2KG, new=P_3_5KG)
        assert adj.wallet_txn_id is not None and adj.billing_invoice_id is not None


# =============================================================================
# J48-J49: cancellation, status rules and B2B classification
# =============================================================================


@pytest.mark.asyncio
async def test_j48_cancel_after_edits_refunds_net_and_post_pickup_cancel_becomes_rto():
    """
    J48 (R24, R25, R26, H-6).
    A) 2 kg Rs.159.30 -> admin edit 3.5 kg (DN Rs.97.35) -> 1 kg (CN Rs.162.25) -> the
       merchant cancels while Ready to ship: REFUND Rs.94.40 = net debited and a
       CREDIT_NOTE of exactly the refund (not the bill). Register nets to Rs.0.
    B) Dispatched 2 kg: an admin "cancel" converts to RTO_INITIATED: RTO_FREIGHT
       Rs.59.00 + DN (bill Rs.218.30), no refund.
    C) Reverse 2 kg with doorstep QC (Rs.218.30, Delhi pickup -> IGST) fails QC
       before pickup: full REFUND Rs.218.30 + CN, adjustment PICKUP_REJECTION_REFUND.
    D) REJECTED_AT_PICKUP on an IN_TRANSIT parcel is refused (H-6): 400, no money moves.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        # A) cancel after edits
        booked = await _book_b2c_2kg(client, accounts, "J48A")
        sid = booked["id"]
        up = await _patch(client, accounts, sid, ADMIN_EMAIL, {"packages": _std_package_patch(booked, 3.5)})
        assert up.status_code == 200, up.text
        down = await _patch(client, accounts, sid, ADMIN_EMAIL, {"packages": _std_package_patch(up.json(), 1.0)})
        assert down.status_code == 200, down.text
        before = await assert_money_invariants(sid)
        invoice = only(before.notes_of(InvoiceNoteType.INVOICE), "INVOICE")
        bal = await get_wallet_balance(merchant_id)
        expected_cn = await next_document_number(InvoiceNoteType.CREDIT_NOTE)
        cancel = await client.post(
            f"/api/v1/shipments/{sid}/cancel", headers=headers(accounts, CUSTOMER_B2C_EMAIL)
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == PickupStatus.CANCELLED.value
        await assert_wallet_step(merchant_id, bal, P_1KG)
        after = await assert_money_invariants(sid)
        step = new_rows(before, after)
        refund = only(step.txns, "cancellation refund")
        assert M(refund.amount) == P_1KG
        assert_gst_note(
            only(step.notes, "cancellation CN"), note_type=InvoiceNoteType.CREDIT_NOTE,
            amount=P_1KG, number=expected_cn, original_invoice=invoice, shipment_id=sid,
        )
        assert _sum(after.txns, BILL_DEBIT_TYPES) == _sum(after.txns, BILL_CREDIT_TYPES) == Decimal("256.65")

        # B) admin cancel after pickup -> RTO
        shipped = await _book_and_dispatch_b2c_2kg(client, accounts, "J48B")
        bid = shipped["id"]
        before = await snapshot(bid)
        bal = await get_wallet_balance(merchant_id)
        rto = await client.post(f"/api/v1/shipments/{bid}/cancel", headers=headers(accounts, ADMIN_EMAIL))
        assert rto.status_code == 200, rto.text
        assert rto.json()["status"] == PickupStatus.RTO_INITIATED.value
        assert M(rto.json()["payment_details"]["total_logistics_cost"]) == P_2KG_RTO
        await assert_wallet_step(merchant_id, bal, Decimal("-59.00"))
        after = await assert_money_invariants(bid)
        step = new_rows(before, after)
        assert _txn_type(only(step.txns, "RTO txn")) == WalletTxnType.RTO_FREIGHT.value
        assert after.txns_of(WalletTxnType.REFUND) == []
        assert_gst_note(
            only(step.notes, "RTO DN"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("59.00"), shipment_id=bid,
        )

        # C) reverse QC failed before pickup -> full refund
        warehouse_id = await _b2c_warehouse(client, accounts)
        reverse = await client.post(
            "/api/v1/shipments",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "order_reference_id": order_ref("J48C"),
                "shipment_type": "REVERSE",
                "service_type": ServiceType.SURFACE_ROAD.value,
                "requested_pickup_date": date.today().isoformat(),
                "product_category": "APPAREL",
                "reason_for_return": "Size mismatch",
                "qc_required": True,
                "qc_notes": "Tags intact, unworn",
                "new_pickup_address": _drop_address(),
                "delivery_address_id": warehouse_id,
                "packages": [_box(STD_BOX_CM, 2.0)],
                "payment_details": _payment(goods=1000.0),
            },
        )
        assert reverse.status_code == 201, reverse.text
        rid = reverse.json()["id"]
        assert M(reverse.json()["payment_details"]["total_logistics_cost"]) == P_2KG_RTO
        before = await assert_money_invariants(rid)
        invoice = only(before.notes_of(InvoiceNoteType.INVOICE), "reverse INVOICE")
        bal = await get_wallet_balance(merchant_id)
        qc_fail = await _patch(
            client, accounts, rid, OPERATIONS_EMAIL,
            {"status": PickupStatus.QC_FAILED.value, "comment": "J48 tags removed at doorstep"},
        )
        assert qc_fail.status_code == 200, qc_fail.text
        await assert_wallet_step(merchant_id, bal, P_2KG_RTO)
        after = await assert_money_invariants(rid)
        step = new_rows(before, after)
        assert M(only(step.txns, "QC refund").amount) == P_2KG_RTO
        assert_gst_note(
            only(step.notes, "QC CN"), note_type=InvoiceNoteType.CREDIT_NOTE,
            amount=P_2KG_RTO, original_invoice=invoice, shipment_id=rid,
        )
        qc_adj = only(step.adjustments, "QC adjustment")
        assert enum_value(qc_adj.reason) == ChargeAdjustmentReason.PICKUP_REJECTION_REFUND.value
        assert qc_adj.wallet_txn_id == only(step.txns, "QC refund").id

        # D) H-6: no pickup rejection once in transit
        moving = await _book_and_dispatch_b2c_2kg(client, accounts, "J48D")
        before = await snapshot(moving["id"])
        refused = await _patch(
            client, accounts, moving["id"], OPERATIONS_EMAIL,
            {"status": PickupStatus.REJECTED_AT_PICKUP.value, "comment": "J48 too late"},
        )
        assert refused.status_code == 400, refused.text
        after = await assert_money_invariants(moving["id"])
        assert new_rows(before, after).txns == []
        assert after.shipment.status == PickupStatus.IN_TRANSIT


@pytest.mark.asyncio
async def test_j49_b2b_comment_only_save_is_free_and_po_number_flips_to_b2b_pricing():
    """
    J49 (R6, R28).
    A) customerb2b LR 4 x 50x40x40 cm, 25 kg: Rs.6,578.50. A save shaped like the B2B
       edit page (comment + the always-sent is_blind_pickup / is_carriers_risk flags)
       changes nothing: no adjustment, no wallet line, no note.
    B) A B2C 2 kg parcel (Rs.159.30) gets a PO number from an admin: it is now B2B
       cargo (10 kg floor + Rs.50 docket) -> Rs.737.50, SPEND Rs.578.20 + DN (taxable
       Rs.490.00), one ADMIN_EDIT adjustment.
    """
    accounts = await load_accounts()
    async with _client() as client:
        dock_id = await _b2b_dock(client, accounts)
        lr = await _book(
            client, accounts, CUSTOMER_B2B_EMAIL, label="J49A",
            pickup_address_id=dock_id, packages=[_box(B2B_BOX_CM, 25.0, 4)],
            payment=_payment(goods=40000.0), product_category="COMMERCIAL",
            drop_pincode=B2B_DROP_PINCODE,
        )
        lid = lr["id"]
        assert M(lr["payment_details"]["total_logistics_cost"]) == P_B2B_4BOX
        before = await assert_money_invariants(lid)
        save = await _patch(
            client, accounts, lid, ADMIN_EMAIL,
            {"comment": "J49 comment-only save", "is_blind_pickup": False, "is_carriers_risk": False},
        )
        assert save.status_code == 200, save.text
        assert M(save.json()["payment_details"]["total_logistics_cost"]) == P_B2B_4BOX
        after = await assert_money_invariants(lid)
        step = new_rows(before, after)
        assert (step.txns, step.notes, step.adjustments) == ([], [], [])

        parcel = await _book_b2c_2kg(client, accounts, "J49B")
        pid = parcel["id"]
        before = await assert_money_invariants(pid)
        invoice = only(before.notes_of(InvoiceNoteType.INVOICE), "INVOICE")
        merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
        bal = await get_wallet_balance(merchant_id)
        po = await _patch(client, accounts, pid, ADMIN_EMAIL, {"service_type": ServiceType.AIR.value})
        assert po.status_code == 200, po.text
        assert M(po.json()["payment_details"]["total_logistics_cost"]) == P_AIR_2KG
        assert po.json()["service_type"] == ServiceType.AIR.value
        await assert_wallet_step(merchant_id, bal, Decimal("-77.88"))
        after = await assert_money_invariants(pid)
        step = new_rows(before, after)
        assert _txn_type(only(step.txns, "Express upgrade txn")) == WalletTxnType.SPEND.value
        assert_gst_note(
            only(step.notes, "Express upgrade DN"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("77.88"), original_invoice=invoice, shipment_id=pid,
        )
        assert_adjustment(only(step.adjustments, "Express adjustment"), reasons={ChargeAdjustmentReason.ADMIN_EDIT}, old=P_2KG, new=P_AIR_2KG)


# =============================================================================
# J50-J53: preview == saved, merchant self-edit, short shipment, separate charges
# =============================================================================


async def _assert_preview_matches_save(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str,
    change: Dict[str, Any],
    *,
    expected_new_total: Decimal,
) -> Dict[str, Any]:
    """Preview writes nothing; the PATCH that follows saves exactly the previewed total."""
    before = await snapshot(sid)
    merchant_id = str(before.shipment.created_by_user_id)
    bal = await get_wallet_balance(merchant_id)
    preview = await _preview(client, accounts, sid, email, change)
    assert preview["rejected_fields"] == [], preview
    assert M(preview["old_total"]) == before.total
    assert M(preview["new_total"]) == expected_new_total
    assert M(preview["delta"]) == expected_new_total - before.total
    expected_action = (
        SettlementAction.DEBIT.value if expected_new_total > before.total else SettlementAction.REFUND.value
    )
    if is_wallet_billed(before):
        assert preview["settlement_action"] == expected_action
        assert preview["note_type"] == (
            InvoiceNoteType.DEBIT_NOTE.value if expected_action == SettlementAction.DEBIT.value else InvoiceNoteType.CREDIT_NOTE.value
        )
    unchanged = await snapshot(sid)
    assert new_rows(before, unchanged) == StepDelta([], [], [], []), "preview must never write"
    assert unchanged.total == before.total
    assert M(await get_wallet_balance(merchant_id)) == M(bal)

    saved = await _patch(client, accounts, sid, email, change)
    assert saved.status_code == 200, saved.text
    assert M(saved.json()["payment_details"]["total_logistics_cost"]) == M(preview["new_total"])
    await assert_money_invariants(sid)
    return saved.json()


@pytest.mark.asyncio
async def test_j50_preview_total_equals_saved_total():
    """
    J50 (R7, R8). For four kinds of change, POST /reprice-preview returns old/new/delta
    and the settlement, writes nothing, and the PATCH that follows saves the same total:
    1) B2C COD: 2 kg COD Rs.1,000 (Rs.182.90) -> 3.5 kg + COD Rs.2,000 = Rs.303.85;
    2) B2B carrier's risk FOV: declared Rs.2,00,000 (Rs.7,050.50) -> Rs.3,00,000 = Rs.7,286.50;
    3) RTO-priced: RTO 2 kg (Rs.218.30) -> 3.5 kg keeps the RTO leg = Rs.359.90;
    4) service type before pickup: Surface Rs.159.30 -> Air Rs.237.18.
    """
    accounts = await load_accounts()
    async with _client() as client:
        cod = await _book_b2c_2kg(client, accounts, "J50-1", is_cod=True)
        assert M(cod["payment_details"]["total_logistics_cost"]) == P_COD1000_2KG
        await _assert_preview_matches_save(
            client, accounts, cod["id"], ADMIN_EMAIL,
            {
                "packages": _std_package_patch(cod, 3.5),
                "payment_details": {
                    "freight_payment_mode": "PREPAID", "is_cod": True, "cod_amount": 2000.0,
                    "shipment_value": 2000.0, "shipment_tax_value": 0.0, "shipment_total_value": 2000.0,
                },
            },
            expected_new_total=P_COD2000_3_5KG,
        )

        dock_id = await _b2b_dock(client, accounts)
        fov = await _book(
            client, accounts, CUSTOMER_B2B_EMAIL, label="J50-2",
            pickup_address_id=dock_id, packages=[_box(B2B_BOX_CM, 25.0, 4)],
            payment=_payment(goods=200000.0, eway_bill_numbers=[EWAY_BILL_NUMBER]),
            product_category="COMMERCIAL", drop_pincode=B2B_DROP_PINCODE, is_carriers_risk=True,
        )
        assert M(fov["payment_details"]["total_logistics_cost"]) == P_B2B_4BOX
        await _assert_preview_matches_save(
            client, accounts, fov["id"], ADMIN_EMAIL,
            {"packages": [_box(B2B_BOX_CM, 40.0, 4, id=fov["packages"][0]["id"])]},
            expected_new_total=P_B2B_4BOX_160KG,
        )

        rto_ship = await _book_and_dispatch_b2c_2kg(client, accounts, "J50-3")
        rto = await _patch(
            client, accounts, rto_ship["id"], ADMIN_EMAIL, {"status": PickupStatus.RTO_INITIATED.value}
        )
        assert rto.status_code == 200, rto.text
        assert M(rto.json()["payment_details"]["total_logistics_cost"]) == P_2KG_RTO
        await _assert_preview_matches_save(
            client, accounts, rto_ship["id"], ADMIN_EMAIL,
            {"packages": _std_package_patch(rto.json(), 3.5)},
            expected_new_total=P_3_5KG_RTO,
        )

        air = await _book_b2c_2kg(client, accounts, "J50-4")
        saved = await _assert_preview_matches_save(
            client, accounts, air["id"], ADMIN_EMAIL,
            {"service_type": ServiceType.AIR.value},
            expected_new_total=P_AIR_2KG,
        )
        assert saved["service_type"] == ServiceType.AIR.value


@pytest.mark.asyncio
async def test_j51_merchant_self_edit_follows_do1_matrix_without_finlock_block():
    """
    J51 (R9, B9, H-5, H-8). customerb2c edits its own 2 kg parcel while Ready to ship:
    3.5 kg -> SPEND Rs.97.35 + DN even if the wallet cannot cover it (no Finlock block
    after booking). After pickup the merchant may still change the COD amount (DO1
    `update-forward-order`, up to and including In Transit): COD Rs.1,000 on goods
    Rs.1,000 -> +Rs.23.60 (COD fee Rs.20 + GST) + DN. After pickup the declared boxes
    (403) and the service type (400, H-8) are refused with nothing changed. Another
    merchant cannot touch the shipment (404, H-5).
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        booked = await _book_b2c_2kg(client, accounts, "J51")
        sid = booked["id"]
        bal = await get_wallet_balance(merchant_id)
        edit = await _patch(
            client, accounts, sid, CUSTOMER_B2C_EMAIL,
            {"comment": "J51 merchant corrects weight", "packages": _std_package_patch(booked, 3.5)},
        )
        assert edit.status_code == 200, edit.text
        assert M(edit.json()["payment_details"]["total_logistics_cost"]) == P_3_5KG
        await assert_wallet_step(merchant_id, bal, Decimal("-97.35"))
        snap = await assert_money_invariants(sid)
        assert enum_value(snap.adjustments[-1].reason) == ChargeAdjustmentReason.CUSTOMER_EDIT.value

        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])
        before = await snapshot(sid)
        bal = await get_wallet_balance(merchant_id)
        cod = await _patch(
            client, accounts, sid, CUSTOMER_B2C_EMAIL,
            {"payment_details": {
                "freight_payment_mode": "PREPAID", "is_cod": True, "cod_amount": 1000.0,
                "shipment_value": 1000.0, "shipment_tax_value": 0.0, "shipment_total_value": 1000.0,
            }},
        )
        assert cod.status_code == 200, cod.text
        assert M(cod.json()["payment_details"]["total_logistics_cost"]) == Decimal("280.25")
        await assert_wallet_step(merchant_id, bal, Decimal("-23.60"))
        after = await assert_money_invariants(sid)
        step = new_rows(before, after)
        assert M(only(step.notes, "COD DN").total_amount) == Decimal("23.60")
        assert enum_value(only(step.adjustments, "COD adjustment").reason) in {ChargeAdjustmentReason.CUSTOMER_EDIT.value, ChargeAdjustmentReason.COD_CHANGE.value}

        boxes = await _patch(
            client, accounts, sid, CUSTOMER_B2C_EMAIL, {"packages": _std_package_patch(cod.json(), 1.0)}
        )
        assert boxes.status_code in (400, 403), boxes.text
        service = await _patch(client, accounts, sid, CUSTOMER_B2C_EMAIL, {"service_type": ServiceType.AIR.value})
        assert service.status_code == 400, service.text
        other = await _patch(client, accounts, sid, CUSTOMER_B2B_EMAIL, {"comment": "J51 not mine"})
        assert other.status_code == 404, other.text
        final = await assert_money_invariants(sid)
        assert new_rows(after, final).txns == []
        assert final.total == Decimal("280.25")


@pytest.mark.asyncio
async def test_j52_short_shipment_partial_delivery_and_damaged_rto_waiver():
    """
    J52 (R22, R23).
    A) customerb2b LR 4 x 50x40x40 cm, 25 kg, COD Rs.10,000: Rs.6,814.50 (COD fee
       Rs.200). Short Shipment -> Attempt partial delivery with 3 boxes and a revised
       COD of Rs.7,500: COD fee Rs.150 -> Rs.6,755.50, REFUND Rs.59.00 + CN,
       delivered_box_count 3, COD collectible Rs.7,500, and a loss ticket for the AWB.
    B) LR 4 boxes Rs.6,578.50 marked DAMAGED; Return to origin with Logismart liable:
       RTO_INITIATED with the RTO charge waived (bill unchanged, no wallet line).
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2B_EMAIL]["id"]
    async with _client() as client:
        # Upgrade customerb2b to BOTH for the multi-flow J52 journey, restoring B2B in finally
        res_upgrade = await client.patch(
            f"/api/v1/users/{merchant_id}",
            json={"service_scope": "BOTH"},
            headers=headers(accounts, ADMIN_EMAIL),
        )
        assert res_upgrade.status_code == 200, res_upgrade.text
        try:
            dock_id = await _b2b_dock(client, accounts)
            lr = await _book(
                client, accounts, CUSTOMER_B2B_EMAIL, label="J52A",
                pickup_address_id=dock_id, packages=[_box(B2B_BOX_CM, 25.0, 4)],
                payment=_payment(goods=10000.0, is_cod=True), product_category="ELECTRONICS",
                drop_pincode=B2B_DROP_PINCODE,
                service_flow="B2C",
                service_option="DELHIVERY_SURFACE",
            )
            sid, awb = lr["id"], lr["tracking_id"]
            assert M(lr["payment_details"]["total_logistics_cost"]) == P_B2B_DLV_4BOX_COD10000
            await _dispatch(client, accounts, CUSTOMER_B2B_EMAIL, dock_id, [sid], service_flow="B2C")
            await _raise_exception(client, accounts, sid, NdrExceptionReason.SHORT_SHIPMENT)
            before = await snapshot(sid)
            invoice = only(before.notes_of(InvoiceNoteType.INVOICE), "INVOICE")
            bal = await get_wallet_balance(merchant_id)
            row = await _action(
                client, accounts, sid, CUSTOMER_B2B_EMAIL,
                {"action": NdrAction.PARTIAL_DELIVERY.value, "delivered_box_count": 3, "revised_cod_amount": 7500.0},
            )
            assert row["status"] == PickupStatus.IN_TRANSIT.value
            await assert_wallet_step(merchant_id, bal, Decimal("59.00"))
            after = await assert_money_invariants(sid)
            assert after.total == P_B2B_DLV_4BOX_COD7500
            assert M(after.payment.cod_amount) == Decimal("7500.00")
            assert after.shipment.delivered_box_count == 3
            step = new_rows(before, after)
            assert_gst_note(
                only(step.notes, "short shipment CN"), note_type=InvoiceNoteType.CREDIT_NOTE,
                amount=Decimal("59.00"), original_invoice=invoice, shipment_id=sid,
            )
            assert enum_value(only(step.adjustments, "short shipment adjustment").reason) in {ChargeAdjustmentReason.SHORT_SHIPMENT.value, ChargeAdjustmentReason.COD_CHANGE.value}
            tickets = await client.get(
                f"/api/v1/support-tickets?search={awb}", headers=headers(accounts, CUSTOMER_B2B_EMAIL)
            )
            assert tickets.status_code == 200, tickets.text
            assert len(tickets.json()) >= 1, "a loss ticket is opened for the missing box"

            damaged = await _book(
                client, accounts, CUSTOMER_B2B_EMAIL, label="J52B",
                pickup_address_id=dock_id, packages=[_box(B2B_BOX_CM, 25.0, 4)],
                payment=_payment(goods=40000.0), product_category="COMMERCIAL",
                drop_pincode=B2B_DROP_PINCODE,
            )
            did = damaged["id"]
            await _dispatch(client, accounts, CUSTOMER_B2B_EMAIL, dock_id, [did], service_flow="B2B")
            await _raise_exception(client, accounts, did, NdrExceptionReason.DAMAGED)
            before = await snapshot(did)
            bal = await get_wallet_balance(merchant_id)
            customer_rto = await client.post(
                f"/api/v1/exceptions/{did}/actions",
                headers=headers(accounts, CUSTOMER_B2B_EMAIL),
                json={"action": NdrAction.RETURN_TO_ORIGIN.value, "logismart_liable": True},
            )
            assert customer_rto.status_code == 403, customer_rto.text
            row = await _action(
                client, accounts, did, ADMIN_EMAIL,
                {"action": NdrAction.RETURN_TO_ORIGIN.value, "logismart_liable": True},
            )
            assert row["status"] == PickupStatus.RTO_INITIATED.value
            await assert_wallet_step(merchant_id, bal, Decimal("0.00"))
            after = await assert_money_invariants(did)
            assert after.total == P_B2B_4BOX
            assert new_rows(before, after).txns == []
        finally:
            res_restore = await client.patch(
                f"/api/v1/users/{merchant_id}",
                json={"service_scope": "B2B"},
                headers=headers(accounts, ADMIN_EMAIL),
            )
            assert res_restore.status_code == 200, res_restore.text


@pytest.mark.asyncio
async def test_j53_additional_charges_get_their_own_debit_note_and_integrity_stays_green():
    """
    J53 (R27, R31, D55). 2 kg Rs.159.30 in transit. Ops raise ADDITIONAL_CHARGES with
    a Mathadi charge of Rs.500 (GST-exclusive). The merchant acknowledges: wallet
    -Rs.590.00 as ADDITIONAL_CHARGE + DEBIT_NOTE Rs.590.00 (taxable Rs.500.00); the
    freight bill stays Rs.159.30. Finally GET /wallet/audit-integrity (owner) passes
    with the four Phase B checks and 0 discrepancies across everything this suite did.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "J53")
        sid = shipment["id"]
        await _raise_exception(
            client, accounts, sid, NdrExceptionReason.ADDITIONAL_CHARGES, charge_amount=500.0
        )
        before = await snapshot(sid)
        invoice = only(before.notes_of(InvoiceNoteType.INVOICE), "INVOICE")
        bal = await get_wallet_balance(merchant_id)
        expected_dn = await next_document_number(InvoiceNoteType.DEBIT_NOTE)
        row = await _action(
            client, accounts, sid, CUSTOMER_B2C_EMAIL, {"action": NdrAction.ACKNOWLEDGE_CHARGES.value}
        )
        assert row["status"] == PickupStatus.IN_TRANSIT.value
        await assert_wallet_step(merchant_id, bal, Decimal("-590.00"))
        after = await assert_money_invariants(sid)
        assert after.total == P_2KG, "Mathadi stays outside the freight bill"
        step = new_rows(before, after)
        charge = only(step.txns, "additional charge txn")
        assert _txn_type(charge) == WalletTxnType.ADDITIONAL_CHARGE.value
        assert M(charge.amount) == Decimal("590.00")
        assert_gst_note(
            only(step.notes, "Mathadi DN"), note_type=InvoiceNoteType.DEBIT_NOTE,
            amount=Decimal("590.00"), number=expected_dn, original_invoice=invoice, shipment_id=sid,
        )

        audit = await client.get("/api/v1/wallet/audit-integrity", headers=headers(accounts, OWNER_EMAIL))
        assert audit.status_code == 200, audit.text
        body = audit.json()
        assert body["passed"] is True, body["discrepancies"]
        assert body["discrepancy_count"] == 0


# =============================================================================
# Race tests R1-R3 (FOR UPDATE lock, idempotency H-4)
# =============================================================================


@pytest.mark.asyncio
async def test_r1_two_measurements_at_once_leave_one_active_basis_and_a_consistent_ledger():
    """
    R1. Two hub measurements of the same parcel arrive together (3.5 kg and 5 kg).
    The shipment row lock serialises them: exactly one active measurement, the bill
    equals the price of that measurement (Rs.256.65 or Rs.354.00), and net debited ==
    bill == GST register. A request may lose with 409 but never half-applies.
    """
    accounts = await load_accounts()
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "R1")
        sid = shipment["id"]
        responses = await asyncio.gather(
            _measure(client, accounts, sid, weight_kg=3.5, remark="R1 scale A"),
            _measure(client, accounts, sid, weight_kg=5.0, remark="R1 scale B"),
        )
        assert all(r.status_code in (200, 409) for r in responses), [r.text for r in responses]
        assert any(r.status_code == 200 for r in responses)
        snap = await assert_money_invariants(sid)
        active = snap.active_measurement
        assert active is not None
        price_by_weight = {Decimal("3.50"): P_3_5KG, Decimal("5.00"): P_5KG}
        assert snap.total == price_by_weight[M(active.chargeable_weight_kg)]


@pytest.mark.asyncio
async def test_r2_edit_racing_an_rto_bills_the_rto_once_and_ends_consistent():
    """
    R2. An admin weight edit (3.5 kg) and an RTO race on one in-transit parcel. Either
    order ends at Rs.359.90 when both succeed (3.5 kg + RTO leg); a 409 loser leaves
    only the winner's price (Rs.256.65 edit-only, Rs.218.30 RTO-only). RTO_FREIGHT is
    booked at most once and net debited == bill.
    """
    accounts = await load_accounts()
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "R2")
        sid = shipment["id"]
        edit, rto = await asyncio.gather(
            _patch(client, accounts, sid, ADMIN_EMAIL, {"packages": _std_package_patch(shipment, 3.5)}),
            _patch(client, accounts, sid, ADMIN_EMAIL, {"status": PickupStatus.RTO_INITIATED.value}),
        )
        assert edit.status_code in (200, 409), edit.text
        assert rto.status_code in (200, 409), rto.text
        expected = {
            (200, 200): P_3_5KG_RTO,
            (200, 409): P_3_5KG,
            (409, 200): P_2KG_RTO,
        }[(edit.status_code, rto.status_code)]
        snap = await assert_money_invariants(sid)
        assert snap.total == expected
        assert len(snap.txns_of(WalletTxnType.RTO_FREIGHT)) == (1 if rto.status_code == 200 else 0)


@pytest.mark.asyncio
async def test_r3_repeated_idempotency_key_never_writes_a_second_ledger_row():
    """
    R3 (H-4). One hub measurement (3.5 kg) sent three times with the same
    Idempotency-Key: the replay returns the stored response, and there is exactly one
    WEIGHT_AUDIT_DEBIT (Rs.97.35), one DN and one adjustment. The same key with a
    different body -> 422. Two simultaneous sends with a fresh key -> one applies, the
    other replays or gets 409; still exactly one new ledger row.
    """
    accounts = await load_accounts()
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "R3")
        sid = shipment["id"]
        before = await snapshot(sid)
        key = f"golden-r3-{uuid.uuid4()}"
        first = await _measure(client, accounts, sid, weight_kg=3.5, idempotency_key=key)
        assert first.status_code == 200, first.text
        replay = await _measure(client, accounts, sid, weight_kg=3.5, idempotency_key=key)
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json(), "same key + same body replays the stored response"
        conflict = await _measure(client, accounts, sid, weight_kg=5.0, idempotency_key=key)
        assert conflict.status_code == 422, conflict.text
        after = await assert_money_invariants(sid)
        step = new_rows(before, after)
        assert M(only(step.txns, "single audit debit").amount) == Decimal("97.35")
        assert len(step.notes) == 1 and len(step.adjustments) == 1
        assert after.total == P_3_5KG

        fresh = f"golden-r3-{uuid.uuid4()}"
        racing = await asyncio.gather(
            _measure(client, accounts, sid, weight_kg=5.0, idempotency_key=fresh),
            _measure(client, accounts, sid, weight_kg=5.0, idempotency_key=fresh),
        )
        assert sorted(r.status_code for r in racing) in ([200, 200], [200, 409]), [r.text for r in racing]
        final = await assert_money_invariants(sid)
        race_step = new_rows(after, final)
        assert M(only(race_step.txns, "single raced debit").amount) == Decimal("97.35")
        assert len(race_step.adjustments) == 1
        assert final.total == P_5KG
