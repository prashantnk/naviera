"""
Golden Suite 10: cross-cutting guards (ship-readiness plan item E2).

- J54: cross-tenant by-id matrix (hard block H-5). Ids created in the guarded test
  tenant (`logismart-test`) are requested by three outsiders and must give 403/404
  without leaking the row:
    a) HEADER SWAP: a real test-tenant token sent with `X-Tenant-Slug: naviera`;
    b) NAVIERA PRINCIPAL: an in-process, NEVER persisted owner of the `naviera`
       tenant (FastAPI dependency override). This reaches the services and the
       repositories with `tenant_id = naviera`, so it proves the queries filter by
       tenant, not just the auth header;
    c) CROSS MERCHANT: `customerb2b` of the same tenant on `customerb2c`'s ids.
  `naviera` is used READ-ONLY: only requests, no writes. Every row the probe could
  write references its user id, which does not exist in `user` (FK), so a broken
  guard fails with a rollback instead of writing; a row-count snapshot of every
  `naviera` table before/after proves nothing was written.
- J55: double submit / races on money endpoints (hard block H-4). Each case runs
  two identical requests concurrently and asserts exactly one ledger effect, then
  checks the `Idempotency-Key` contract where the plan requires it (B13): replay of
  the same key + same body returns the stored response, the same key with a
  different body (or a different resource) returns 422.

Self-contained: the session fixture in `golden_journeys/conftest.py` resets the test
tenant, and this suite creates every row it needs through the API. It never reads
another suite's state files.

Spring analogy: J54 is a MockMvc security matrix (`@WithMockUser` of another tenant on
every `/{id}` route); J55 is a `CompletableFuture.allOf(first, second)` race test against a
`@Transactional` service with an idempotent-receiver filter.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import httpx
import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport
from sqlalchemy import text
from sqlmodel import col, select

from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.delhivery_modules import (
    BillingInvoice,
    InvoiceNoteType,
    SupportTicket,
    WeightDispute,
    WeightDisputeClaimStatus,
)
from app.models.manifests import Manifest, ManifestStatus
from app.models.pickups import (
    Address,
    FreightPaymentMode,
    NdrAction,
    NdrExceptionReason,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ServiceType,
    ShipmentActivity,
)
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.models.wallet import WalletTransaction, WalletTxnStatus, WalletTxnType

from .golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OPERATIONS_EMAIL,
    OWNER_EMAIL,
    GoldenEnvError,
    GoldenSessionLocal,
    find_seeded_address_id,
    get_tenant_id,
    get_wallet_balance,
    headers,
    load_accounts,
    make_bank_utr,
    make_utr,
    order_ref,
    read_otp_as_merchant,
)

# --- Constants -------------------------------------------------------------

SECOND_TENANT_SLUG = "naviera"
"""The other tenant used READ-ONLY for J54 (requests only; it has no users)."""

FORBIDDEN_SECOND_TENANT_SLUGS: FrozenSet[str] = frozenset({"logismart"})
ASGI_BASE_URL = "http://test"
HTTP_TIMEOUT_SECONDS = 60.0
IDEMPOTENCY_HEADER = "Idempotency-Key"

DENIED: FrozenSet[int] = frozenset({403, 404})
DENIED_OR_REJECTED: FrozenSet[int] = frozenset({400, 403, 404})
"""For ids passed in a BODY: a 400 ("not eligible / not found") is also a correct refusal."""

DUPLICATE_REFUSED: FrozenSet[int] = frozenset({400, 409})
NDR_ACTION_DIFF_KEY = "ndr_action"
"""Activity diff key that records which NDR action was applied."""
"""Second, unkeyed copy of a one-shot action: refused by the state machine or a lock."""

IN_FLIGHT_OR_SUCCESS: FrozenSet[int] = frozenset({200, 201, 409})
"""Concurrent copy that shares the same Idempotency-Key: replayed (2xx) or 'in flight' (409)."""

IDEMPOTENCY_MISMATCH_STATUS = 422
SUCCESS_STATUSES: FrozenSet[int] = frozenset({200, 201})

WALLET_TOPUP_INR = 20_000.0
RACE_RECHARGE_INR = 777.0
SECOND_RECHARGE_INR = 333.0
COD_GOODS_INR = 1_200.0
DECLARED_WEIGHT_KG = 0.5
EDITED_WEIGHT_KG = 2.0
MEASURED_WEIGHT_KG = 3.0
OTHER_MEASURED_WEIGHT_KG = 3.5
CLAIMED_WEIGHT_G = 500.0
CHARGE_AMOUNT_INR = 100.0
MONEY_DECIMALS = 2

DELIVERY_ADDRESS = {
    "name": "Xcut Consignee",
    "phone": "9810011177",
    "address_line1": "Flat 7, DLF Phase 2",
    "city": "Gurugram",
    "state": "Haryana",
    "pincode": "122002",
    "country": "IN",
    "category": "HOME",
}

BILL_DEBIT_TYPES: FrozenSet[WalletTxnType] = frozenset(
    {
        WalletTxnType.SPEND,
        WalletTxnType.WEIGHT_AUDIT_DEBIT,
        WalletTxnType.RTO_FREIGHT,
        WalletTxnType.FREIGHT_COLLECTION,
    }
)
"""Mirror of plan §2.0 `BILL_DEBIT_TYPES` (kept local so collection never depends on wave-1 imports)."""

BILL_CREDIT_TYPES: FrozenSet[WalletTxnType] = frozenset({WalletTxnType.REFUND})

# Tables whose `naviera` row counts must not change during J54 (only those that exist
# and carry `tenant_id` are counted; see `_second_tenant_row_counts`).
SECOND_TENANT_GUARD_TABLES: Sequence[str] = (
    "user",
    "addresses",
    "pickups",
    "manifests",
    "user_wallets",
    "wallet_transactions",
    "billing_invoices",
    "cod_remittances",
    "support_tickets",
    "weight_disputes",
    "tenant_settings_history",
    "shipment_charge_adjustments",
    "shipment_measurements",
    "idempotency_keys",
)

# --- Small helpers ---------------------------------------------------------


def _client() -> httpx.AsyncClient:
    """In-process ASGI client (no running server needed)."""
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url=ASGI_BASE_URL, timeout=HTTP_TIMEOUT_SECONDS
    )


def _with_key(base: Mapping[str, str], key: Optional[str]) -> Dict[str, str]:
    """Returns a copy of `base` headers plus an Idempotency-Key when `key` is given."""
    merged = dict(base)
    if key is not None:
        merged[IDEMPOTENCY_HEADER] = key
    return merged


def _new_key(label: str) -> str:
    """Returns a fresh Idempotency-Key for one case."""
    return f"xcut-{label}-{uuid.uuid4()}"


def _money(value: Any) -> float:
    """Rounds a money value to the paisa for exact comparisons."""
    return round(float(value or 0.0), MONEY_DECIMALS)


async def _gather(*calls: Awaitable[httpx.Response]) -> List[httpx.Response]:
    """Fires the requests concurrently on the same event loop and returns all responses."""
    return list(await asyncio.gather(*calls))


def _statuses(responses: Sequence[httpx.Response]) -> List[int]:
    """Status codes of a batch of responses (for assertion messages)."""
    return [r.status_code for r in responses]


def _one_winner(responses: Sequence[httpx.Response], loser_statuses: FrozenSet[int]) -> httpx.Response:
    """
    Asserts exactly one response succeeded and every other one is in `loser_statuses`.

    Returns:
        The winning response.
    """
    winners = [r for r in responses if r.status_code in SUCCESS_STATUSES]
    losers = [r for r in responses if r.status_code not in SUCCESS_STATUSES]
    assert len(winners) == 1, f"Expected exactly one success, got {_statuses(responses)}: {[r.text for r in responses]}"
    assert all(r.status_code in loser_statuses for r in losers), (
        f"Duplicate copy must be refused with {sorted(loser_statuses)}, got {_statuses(responses)}: "
        f"{[r.text for r in losers]}"
    )
    return winners[0]


def _keyed_race_winner(responses: Sequence[httpx.Response]) -> httpx.Response:
    """
    Two concurrent requests with the SAME Idempotency-Key: at least one succeeds, the
    other is either a replay with an identical body or a 409 "in flight".
    """
    assert all(r.status_code in IN_FLIGHT_OR_SUCCESS for r in responses), (
        f"Keyed race statuses {_statuses(responses)}: {[r.text for r in responses]}"
    )
    winners = [r for r in responses if r.status_code in SUCCESS_STATUSES]
    assert winners, f"No keyed request succeeded: {_statuses(responses)}"
    first = winners[0]
    for other in winners[1:]:
        assert other.status_code == first.status_code and other.json() == first.json(), (
            "A concurrent replay of the same Idempotency-Key must return the identical response"
        )
    return first


def _assert_replay(original: httpx.Response, replay: httpx.Response) -> None:
    """Same key + same body later on: identical status and JSON (H-4)."""
    assert replay.status_code == original.status_code, (replay.status_code, replay.text)
    assert replay.json() == original.json(), "Idempotent replay returned a different body"


def _assert_key_mismatch(resp: httpx.Response) -> None:
    """Same key + different request: 422 (H-4), never a replay of the other request."""
    assert resp.status_code == IDEMPOTENCY_MISMATCH_STATUS, (resp.status_code, resp.text)


# --- DB reads (always filtered by the guarded test tenant) -----------------


def _raw(value: Any) -> Any:
    """Raw value of an Enum member, or the value itself (some columns load as plain strings)."""
    return value.value if isinstance(value, Enum) else value


async def _shipment_txns(shipment_id: str) -> List[WalletTransaction]:
    """Every wallet transaction of one shipment inside the test tenant."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        rows = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.tenant_id == tenant_id,
                    WalletTransaction.shipment_id == uuid.UUID(shipment_id),
                )
            )
        ).all()
        await session.rollback()
    return list(rows)


async def _count_txns(shipment_id: str, txn_type: WalletTxnType) -> int:
    """Number of COMPLETED wallet rows of `txn_type` for one shipment."""
    return sum(
        1
        for t in await _shipment_txns(shipment_id)
        if t.txn_type == txn_type and t.status == WalletTxnStatus.COMPLETED
    )


async def _net_debited(shipment_id: str) -> float:
    """Plan §2.0: Σ BILL_DEBIT − Σ BILL_CREDIT over COMPLETED rows of one shipment."""
    total = 0.0
    for txn in await _shipment_txns(shipment_id):
        if txn.status != WalletTxnStatus.COMPLETED:
            continue
        if txn.txn_type in BILL_DEBIT_TYPES:
            total += float(txn.amount)
        elif txn.txn_type in BILL_CREDIT_TYPES:
            total -= float(txn.amount)
    return round(total, MONEY_DECIMALS)


async def _bill_total(shipment_id: str) -> float:
    """`payment_details.total_logistics_cost` of one shipment (the bill)."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        row = (
            await session.exec(
                select(PaymentDetails)
                .join(PickupRequest, PickupRequest.id == PaymentDetails.pickup_id)
                .where(
                    PickupRequest.tenant_id == tenant_id,
                    PickupRequest.id == uuid.UUID(shipment_id),
                )
            )
        ).first()
        await session.rollback()
    assert row is not None, f"No payment_details for shipment {shipment_id}"
    return _money(row.total_logistics_cost)


def _note_belongs_to(note: BillingInvoice, shipment_id: str) -> bool:
    """True when a GST document is for `shipment_id` (new `shipment_id` column or legacy line items)."""
    linked = getattr(note, "shipment_id", None)
    if linked is not None:
        return str(linked) == shipment_id
    return any(
        isinstance(item, dict) and item.get("shipment_id") == shipment_id
        for item in (note.line_items or [])
    )


async def _count_notes(shipment_id: str, note_type: InvoiceNoteType) -> int:
    """Number of GST documents of `note_type` issued for one shipment in the test tenant."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        notes = (
            await session.exec(
                select(BillingInvoice).where(
                    BillingInvoice.tenant_id == tenant_id,
                    BillingInvoice.note_type == note_type.value,
                )
            )
        ).all()
        await session.rollback()
    return sum(1 for n in notes if _note_belongs_to(n, shipment_id))


async def _count_pickup_rows(table: str, shipment_id: str, extra_where: str = "") -> int:
    """
    Counts rows of a Phase B table (`shipment_charge_adjustments`, `shipment_measurements`)
    for one shipment in the test tenant. Raw SQL on purpose: the table names are fixed by
    migrations M-B1/M-B2, while their SQLModel classes are still being mapped in wave 1.
    """
    allowed = {"shipment_charge_adjustments", "shipment_measurements"}
    assert table in allowed, table
    tenant_id = await get_tenant_id()
    sql = f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id AND pickup_id = :pickup_id {extra_where}"
    async with GoldenSessionLocal() as session:
        count = (
            await session.execute(
                text(sql), {"tenant_id": tenant_id, "pickup_id": uuid.UUID(shipment_id)}
            )
        ).scalar_one()
        await session.rollback()
    return int(count)


async def _count_status_transitions(shipment_id: str, new_status: PickupStatus) -> int:
    """Number of activity rows that moved the shipment INTO `new_status`."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        rows = (
            await session.exec(
                select(ShipmentActivity)
                .join(PickupRequest, PickupRequest.id == ShipmentActivity.pickup_id)
                .where(
                    PickupRequest.tenant_id == tenant_id,
                    ShipmentActivity.pickup_id == uuid.UUID(shipment_id),
                )
            )
        ).all()
        await session.rollback()
    return sum(
        1
        for a in rows
        if isinstance((a.diff or {}).get("status"), dict)
        and (a.diff or {})["status"].get("new") == new_status.value
    )


async def _count_ndr_actions(shipment_id: str, action: NdrAction) -> int:
    """Number of activity rows that applied one NDR action to the shipment (test tenant)."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        rows = (
            await session.exec(
                select(ShipmentActivity)
                .join(PickupRequest, PickupRequest.id == ShipmentActivity.pickup_id)
                .where(
                    PickupRequest.tenant_id == tenant_id,
                    ShipmentActivity.pickup_id == uuid.UUID(shipment_id),
                )
            )
        ).all()
        await session.rollback()
    return sum(1 for a in rows if (a.diff or {}).get(NDR_ACTION_DIFF_KEY) == action.value)


async def _count_shipments_with_ref(order_reference_id: str) -> int:
    """Number of shipments in the test tenant with one order reference."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        rows = (
            await session.exec(
                select(PickupRequest.id).where(
                    PickupRequest.tenant_id == tenant_id,
                    PickupRequest.order_reference_id == order_reference_id,
                )
            )
        ).all()
        await session.rollback()
    return len(rows)


async def _load_second_tenant() -> Tenant:
    """
    Loads the `naviera` tenant READ-ONLY (no write ever targets it).

    Raises:
        GoldenEnvError: When the slug is a forbidden live slug or the tenant is missing.
    """
    if SECOND_TENANT_SLUG in FORBIDDEN_SECOND_TENANT_SLUGS or SECOND_TENANT_SLUG == GOLDEN_TENANT_SLUG:
        raise GoldenEnvError(f"J54 second tenant {SECOND_TENANT_SLUG!r} is not allowed")
    async with GoldenSessionLocal() as session:
        tenant = (
            await session.exec(select(Tenant).where(Tenant.slug == SECOND_TENANT_SLUG))
        ).first()
        await session.rollback()
    if tenant is None:
        raise GoldenEnvError(f"J54 needs the existing tenant {SECOND_TENANT_SLUG!r} (read-only)")
    return tenant


async def _second_tenant_row_counts(tenant_id: uuid.UUID) -> Dict[str, int]:
    """SELECT-only row counts of every guarded table that has a `tenant_id` column."""
    counts: Dict[str, int] = {}
    async with GoldenSessionLocal() as session:
        present = {
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
                    )
                )
            ).all()
        }
        for table in SECOND_TENANT_GUARD_TABLES:
            if table not in present:
                continue
            counts[table] = int(
                (
                    await session.execute(
                        text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :tenant_id'),
                        {"tenant_id": tenant_id},
                    )
                ).scalar_one()
            )
        await session.rollback()
    return counts


# --- API flows (test tenant only) ------------------------------------------


def _booking_payload(
    warehouse_id: str,
    label: str,
    *,
    is_cod: bool = False,
    weight_kg: float = DECLARED_WEIGHT_KG,
    goods_value: float = COD_GOODS_INR,
) -> Dict[str, Any]:
    """B2C forward PREPAID booking body from the seeded Gurugram warehouse."""
    return {
        "order_reference_id": order_ref(label),
        "shipment_type": "FORWARD",
        "service_type": ServiceType.SURFACE_ROAD.value,
        "requested_pickup_date": date.today().isoformat(),
        "product_category": "ELECTRONICS",
        "pickup_address_id": warehouse_id,
        "new_delivery_address": dict(DELIVERY_ADDRESS),
        "packages": [
            {
                "length": 20.0,
                "breadth": 15.0,
                "height": 10.0,
                "dimension_unit": "CM",
                "weight": weight_kg,
                "weight_unit": "KG",
                "box_count": 1,
                "description": f"Xcut {label}",
            }
        ],
        "payment_details": {
            "freight_payment_mode": FreightPaymentMode.PREPAID.value,
            "is_cod": is_cod,
            "cod_amount": goods_value if is_cod else 0.0,
            "shipment_value": goods_value,
            "shipment_tax_value": 0.0,
            "shipment_total_value": goods_value,
            "add_shipping_to_cod": False,
        },
    }


async def _book(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], warehouse_id: str, label: str, **kwargs: Any
) -> Dict[str, Any]:
    """Books one B2C PREPAID shipment as `customerb2c` and returns the shipment JSON."""
    resp = await client.post(
        "/api/v1/shipments",
        headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        json=_booking_payload(warehouse_id, label, **kwargs),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_pur(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], warehouse_id: str, shipment_ids: Sequence[str]
) -> Dict[str, Any]:
    """Creates a B2C pickup request with the given OPEN shipments."""
    resp = await client.post(
        "/api/v1/manifests",
        headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        json={
            "pickup_address_id": warehouse_id,
            "scheduled_date": date.today().isoformat(),
            "time_slot": "10:00 - 14:00",
            "service_flow": "B2C",
            "is_blind_pickup": False,
            "shipment_ids": list(shipment_ids),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _dispatch_request(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], pur_id: str, picked: Sequence[str]
) -> Awaitable[httpx.Response]:
    """Ops 'Confirm picked up' request (not awaited, so callers can race it)."""
    return client.post(
        f"/api/v1/manifests/{pur_id}/dispatch",
        headers=headers(accounts, OPERATIONS_EMAIL),
        json={"picked_shipment_ids": list(picked)},
    )


async def _book_and_dispatch(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], warehouse_id: str, label: str, **kwargs: Any
) -> Dict[str, Any]:
    """Books a shipment, puts it on a PUR and dispatches it (IN_TRANSIT). Returns the shipment JSON."""
    shipment = await _book(client, accounts, warehouse_id, label, **kwargs)
    pur = await _create_pur(client, accounts, warehouse_id, [shipment["id"]])
    resp = await _dispatch_request(client, accounts, pur["id"], [shipment["id"]])
    assert resp.status_code == 200, resp.text
    shipment["manifest_id"] = pur["id"]
    return shipment


async def _deliver(client: httpx.AsyncClient, accounts: Mapping[str, Any], shipment_id: str) -> None:
    """Delivers an IN_TRANSIT shipment with the OTP read through the merchant token."""
    otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2C_EMAIL, shipment_id)
    resp = await client.patch(
        f"/api/v1/shipments/{shipment_id}",
        headers=headers(accounts, OPERATIONS_EMAIL),
        json={
            "status": PickupStatus.COMPLETED.value,
            "delivery_otp": otp,
            "pod_received_by": "Xcut Consignee",
        },
    )
    assert resp.status_code == 200, resp.text


async def _pending_recharge(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], amount: float
) -> str:
    """UPI intent + customer confirm (PENDING, awaiting the admin). Returns the transaction id."""
    cust = headers(accounts, CUSTOMER_B2C_EMAIL)
    intent = await client.post("/api/v1/wallet/recharge/upi-intent", headers=cust, json={"amount": amount})
    assert intent.status_code == 200, intent.text
    txn_id = intent.json()["transaction_id"]
    confirm = await client.post(
        f"/api/v1/wallet/recharge/{txn_id}/confirm", headers=cust, json={"utr_number": make_utr()}
    )
    assert confirm.status_code == 200, confirm.text
    return str(txn_id)


async def _ensure_funded(client: httpx.AsyncClient, accounts: Mapping[str, Any]) -> None:
    """Tops up `customerb2c` once so prepaid bookings never hit a wallet guard."""
    if await get_wallet_balance(accounts[CUSTOMER_B2C_EMAIL]["id"]) >= WALLET_TOPUP_INR / 2:
        return
    txn_id = await _pending_recharge(client, accounts, WALLET_TOPUP_INR)
    approve = await client.post(
        f"/api/v1/wallet/recharge/{txn_id}/approve", headers=headers(accounts, ADMIN_EMAIL)
    )
    assert approve.status_code == 200, approve.text


async def _audit_weight(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], shipment_id: str, weight_kg: float
) -> None:
    """Hub weight audit by ops (creates the weight dispute row)."""
    resp = await client.post(
        f"/api/v1/shipments/{shipment_id}/audit-weight",
        headers=headers(accounts, OPERATIONS_EMAIL),
        json={"audited_weight_kg": weight_kg},
    )
    assert resp.status_code == 200, resp.text


async def _dispute_id(client: httpx.AsyncClient, accounts: Mapping[str, Any], awb: str) -> str:
    """Id of the weight dispute of one AWB (customer view)."""
    resp = await client.get(
        f"/api/v1/disputes/weight-mismatch?search={awb}", headers=headers(accounts, CUSTOMER_B2C_EMAIL)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1, rows
    return str(rows[0]["id"])


async def _raise_claim(client: httpx.AsyncClient, accounts: Mapping[str, Any], awb: str) -> None:
    """Customer raises a weight claim on one AWB."""
    resp = await client.post(
        "/api/v1/disputes/weight-mismatch/claims",
        headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        json={"tracking_ids": [awb], "claimed_weight_g": CLAIMED_WEIGHT_G, "claim_remarks": "Xcut claim"},
    )
    assert resp.status_code == 200, resp.text


async def _raise_charge_exception(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], shipment_id: str
) -> None:
    """Ops puts an IN_TRANSIT shipment on hold with an Additional Charges exception."""
    resp = await client.patch(
        f"/api/v1/shipments/{shipment_id}",
        headers=headers(accounts, OPERATIONS_EMAIL),
        json={
            "status": PickupStatus.EXCEPTION.value,
            "ndr_reason": NdrExceptionReason.ADDITIONAL_CHARGES.value,
            "charge_amount": CHARGE_AMOUNT_INR,
            "ndr_remark": "Xcut union entry fee",
        },
    )
    assert resp.status_code == 200, resp.text


# =============================================================================
# J54: cross-tenant by-id matrix
# =============================================================================


@dataclass
class World:
    """Rows created in the test tenant that the outsiders try to reach."""

    warehouse_id: str
    delivered_id: str
    delivered_awb: str
    open_id: str
    open_awb: str
    scheduled_pur_id: str
    picked_pur_id: str
    pending_txn_id: str
    spend_txn_id: str
    invoice_id: str
    invoice_number: str
    remittance_id: str
    dispute_id: str
    ticket_id: str
    ticket_number: str
    customer_b2c_id: str
    tenant_id: str
    secrets: List[str] = field(default_factory=list)

    def leak_markers(self) -> List[str]:
        """Strings that must never appear in an outsider's response body."""
        return [
            self.delivered_awb,
            self.open_awb,
            self.invoice_number,
            self.ticket_number,
            self.delivered_id,
            self.open_id,
            *self.secrets,
        ]


@dataclass(frozen=True)
class Probe:
    """One by-id request of the matrix."""

    name: str
    method: str
    route: str
    path: str
    body: Optional[Dict[str, Any]] = None
    allowed: FrozenSet[int] = DENIED
    customer_scoped: bool = True
    owner_email: Optional[str] = None
    """When set, a GET positive control as this account must NOT be 404."""


async def _build_world(client: httpx.AsyncClient, accounts: Mapping[str, Any]) -> World:
    """Creates every target row through the API (test tenant only)."""
    await _ensure_funded(client, accounts)
    warehouse_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)

    delivered = await _book(client, accounts, warehouse_id, "J54-DLV", is_cod=True)
    picked_pur = await _create_pur(client, accounts, warehouse_id, [delivered["id"]])
    dispatch = await _dispatch_request(client, accounts, picked_pur["id"], [delivered["id"]])
    assert dispatch.status_code == 200, dispatch.text
    await _audit_weight(client, accounts, delivered["id"], MEASURED_WEIGHT_KG)
    await _deliver(client, accounts, delivered["id"])
    remit = await client.post(
        "/api/v1/remittances",
        headers=headers(accounts, ADMIN_EMAIL),
        json={
            "shipment_ids": [delivered["id"]],
            "bank_utr": make_bank_utr(),
            "expected_total": COD_GOODS_INR,
        },
    )
    assert remit.status_code == 201, remit.text

    open_shipment = await _book(client, accounts, warehouse_id, "J54-OPEN")
    scheduled_pur = await _create_pur(client, accounts, warehouse_id, [open_shipment["id"]])

    ticket = await client.post(
        "/api/v1/support-tickets",
        headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        json={
            "category_group": "SHIPMENT_ISSUE",
            "sub_category": "Delivery Query",
            "subject": f"Xcut J54 ticket {delivered['tracking_id']}",
            "description": "Cross-tenant probe target",
            "tracking_id": delivered["tracking_id"],
        },
    )
    assert ticket.status_code == 201, ticket.text

    pending_txn_id = await _pending_recharge(client, accounts, SECOND_RECHARGE_INR)
    spend = [t for t in await _shipment_txns(delivered["id"]) if t.txn_type == WalletTxnType.SPEND]
    assert len(spend) == 1, spend

    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        invoices = (
            await session.exec(
                select(BillingInvoice).where(
                    BillingInvoice.tenant_id == tenant_id,
                    BillingInvoice.note_type == InvoiceNoteType.INVOICE.value,
                )
            )
        ).all()
        await session.rollback()
    invoice = next(i for i in invoices if _note_belongs_to(i, delivered["id"]))

    return World(
        warehouse_id=warehouse_id,
        delivered_id=delivered["id"],
        delivered_awb=delivered["tracking_id"],
        open_id=open_shipment["id"],
        open_awb=open_shipment["tracking_id"],
        scheduled_pur_id=scheduled_pur["id"],
        picked_pur_id=picked_pur["id"],
        pending_txn_id=pending_txn_id,
        spend_txn_id=str(spend[0].id),
        invoice_id=str(invoice.id),
        invoice_number=invoice.invoice_number,
        remittance_id=str(remit.json()["id"]),
        dispute_id=await _dispute_id(client, accounts, delivered["tracking_id"]),
        ticket_id=str(ticket.json()["id"]),
        ticket_number=str(ticket.json()["ticket_number"]),
        customer_b2c_id=accounts[CUSTOMER_B2C_EMAIL]["id"],
        tenant_id=str(tenant_id),
    )


def _probes(w: World) -> List[Probe]:
    """The by-id matrix: every shipment, manifest, wallet, invoice, remittance, dispute,
    support-ticket and Phase B endpoint that takes an id of the test tenant."""
    s_dlv, s_open = w.delivered_id, w.open_id
    measurement = {"source": "HUB", "weight_kg": MEASURED_WEIGHT_KG}
    return [
        # --- Shipments (incl. Phase B) -------------------------------------
        Probe("shipment.get", "GET", "/api/v1/shipments/{shipment_id}", f"/api/v1/shipments/{s_dlv}", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("shipment.timeline", "GET", "/api/v1/shipments/{shipment_id}/timeline", f"/api/v1/shipments/{s_dlv}/timeline", owner_email=ADMIN_EMAIL),
        Probe("shipment.label", "GET", "/api/v1/shipments/{shipment_id}/label", f"/api/v1/shipments/{s_open}/label", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("shipment.invoice_pdf", "GET", "/api/v1/shipments/{shipment_id}/invoice-pdf", f"/api/v1/shipments/{s_dlv}/invoice-pdf", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("shipment.charges", "GET", "/api/v1/shipments/{shipment_id}/charges", f"/api/v1/shipments/{s_dlv}/charges", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("shipment.reprice_preview", "POST", "/api/v1/shipments/{shipment_id}/reprice-preview", f"/api/v1/shipments/{s_open}/reprice-preview", {"comment": "xcut probe"}),
        Probe("shipment.measurements", "POST", "/api/v1/shipments/{shipment_id}/measurements", f"/api/v1/shipments/{s_open}/measurements", measurement, customer_scoped=False),
        Probe("shipment.audit_weight", "POST", "/api/v1/shipments/{shipment_id}/audit-weight", f"/api/v1/shipments/{s_open}/audit-weight", {"audited_weight_kg": MEASURED_WEIGHT_KG}, customer_scoped=False),
        Probe("shipment.patch", "PATCH", "/api/v1/shipments/{shipment_id}", f"/api/v1/shipments/{s_open}", {"comment": "xcut probe"}),
        Probe("shipment.put", "PUT", "/api/v1/shipments/{shipment_id}", f"/api/v1/shipments/{s_open}", {"comment": "xcut probe"}),
        Probe("shipment.cancel", "POST", "/api/v1/shipments/{shipment_id}/cancel", f"/api/v1/shipments/{s_open}/cancel"),
        Probe("shipment.appointment", "PATCH", "/api/v1/shipments/{shipment_id}/appointment", f"/api/v1/shipments/{s_open}/appointment", {"po_number": "XCUT-PO-1"}),
        Probe("shipment.resolve_exception", "POST", "/api/v1/shipments/{shipment_id}/resolve-exception", f"/api/v1/shipments/{s_open}/resolve-exception", {"action": "DELIVER_WITHOUT_APPOINTMENT"}),
        Probe("exception.action", "POST", "/api/v1/exceptions/{shipment_id}/actions", f"/api/v1/exceptions/{s_open}/actions", {"action": NdrAction.REATTEMPT.value}),
        # --- Manifests / pickup requests -----------------------------------
        Probe("manifest.add_shipments", "POST", "/api/v1/manifests/{manifest_id}/shipments", f"/api/v1/manifests/{w.scheduled_pur_id}/shipments", {"shipment_ids": [s_open]}),
        Probe("manifest.cancel", "POST", "/api/v1/manifests/{manifest_id}/cancel", f"/api/v1/manifests/{w.scheduled_pur_id}/cancel"),
        Probe("manifest.out_for_pickup", "POST", "/api/v1/manifests/{manifest_id}/out-for-pickup", f"/api/v1/manifests/{w.scheduled_pur_id}/out-for-pickup", customer_scoped=False),
        Probe("manifest.not_picked", "POST", "/api/v1/manifests/{manifest_id}/not-picked", f"/api/v1/manifests/{w.scheduled_pur_id}/not-picked", {"failure_reason": "xcut probe"}, customer_scoped=False),
        Probe("manifest.dispatch", "POST", "/api/v1/manifests/{manifest_id}/dispatch", f"/api/v1/manifests/{w.scheduled_pur_id}/dispatch", {"picked_shipment_ids": [s_open]}, customer_scoped=False),
        Probe("manifest.labels", "GET", "/api/v1/manifests/{manifest_id}/labels", f"/api/v1/manifests/{w.scheduled_pur_id}/labels", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("manifest.pdf", "GET", "/api/v1/manifests/{manifest_id}/pdf", f"/api/v1/manifests/{w.picked_pur_id}/pdf", owner_email=CUSTOMER_B2C_EMAIL),
        # --- Wallet ---------------------------------------------------------
        Probe("wallet.recharge_status", "GET", "/api/v1/wallet/recharge/{transaction_id}/status", f"/api/v1/wallet/recharge/{w.pending_txn_id}/status", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("wallet.recharge_confirm", "POST", "/api/v1/wallet/recharge/{transaction_id}/confirm", f"/api/v1/wallet/recharge/{w.pending_txn_id}/confirm", {"utr_number": make_utr()}),
        Probe("wallet.recharge_approve", "POST", "/api/v1/wallet/recharge/{transaction_id}/approve", f"/api/v1/wallet/recharge/{w.pending_txn_id}/approve", customer_scoped=False),
        Probe("wallet.recharge_reject", "POST", "/api/v1/wallet/recharge/{transaction_id}/reject", f"/api/v1/wallet/recharge/{w.pending_txn_id}/reject", customer_scoped=False),
        Probe("wallet.receipt_pdf", "GET", "/api/v1/wallet/transactions/{txn_id}/receipt-pdf", f"/api/v1/wallet/transactions/{w.spend_txn_id}/receipt-pdf", owner_email=CUSTOMER_B2C_EMAIL),
        # --- Invoices / GST notes ------------------------------------------
        Probe("invoice.get", "GET", "/api/v1/invoices/{identifier}", f"/api/v1/invoices/{w.invoice_id}", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("invoice.get_by_number", "GET", "/api/v1/invoices/{identifier}", f"/api/v1/invoices/{w.invoice_number}", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("invoice.pdf", "GET", "/api/v1/invoices/{identifier}/pdf", f"/api/v1/invoices/{w.invoice_id}/pdf", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("invoice.csv", "GET", "/api/v1/invoices/{identifier}/transactions-csv", f"/api/v1/invoices/{w.invoice_id}/transactions-csv", owner_email=CUSTOMER_B2C_EMAIL),
        # --- Remittances ----------------------------------------------------
        Probe("remittance.get", "GET", "/api/v1/remittances/{identifier}", f"/api/v1/remittances/{w.remittance_id}", owner_email=ADMIN_EMAIL),
        Probe("remittance.csv", "GET", "/api/v1/remittances/{identifier}/csv", f"/api/v1/remittances/{w.remittance_id}/csv", owner_email=ADMIN_EMAIL),
        Probe("remittance.create", "POST", "/api/v1/remittances", "/api/v1/remittances", {"shipment_ids": [s_dlv], "bank_utr": make_bank_utr(), "expected_total": COD_GOODS_INR}, DENIED_OR_REJECTED, customer_scoped=False),
        # --- Weight disputes -------------------------------------------------
        Probe("dispute.resolve", "PATCH", "/api/v1/disputes/weight-mismatch/{dispute_id}/resolve", f"/api/v1/disputes/weight-mismatch/{w.dispute_id}/resolve", {"claim_status": WeightDisputeClaimStatus.ACCEPTED.value, "claim_remarks": "xcut probe"}, customer_scoped=False),
        Probe("dispute.claim", "POST", "/api/v1/disputes/weight-mismatch/claims", "/api/v1/disputes/weight-mismatch/claims", {"tracking_ids": [w.delivered_awb], "claimed_weight_g": CLAIMED_WEIGHT_G, "claim_remarks": "xcut probe"}, DENIED_OR_REJECTED),
        # --- Support tickets -------------------------------------------------
        Probe("ticket.get", "GET", "/api/v1/support-tickets/{ticket_id}", f"/api/v1/support-tickets/{w.ticket_id}", owner_email=CUSTOMER_B2C_EMAIL),
        Probe("ticket.message", "POST", "/api/v1/support-tickets/{ticket_id}/messages", f"/api/v1/support-tickets/{w.ticket_id}/messages", {"message": "xcut probe"}),
        Probe("ticket.status", "PATCH", "/api/v1/support-tickets/{ticket_id}/status", f"/api/v1/support-tickets/{w.ticket_id}/status", {"status": "RESOLVED"}),
        # --- Addresses / users / tenant -------------------------------------
        Probe("address.patch", "PATCH", "/api/v1/addresses/{address_id}", f"/api/v1/addresses/{w.warehouse_id}", {"name": "xcut probe"}),
        Probe("address.delete", "DELETE", "/api/v1/addresses/{address_id}", f"/api/v1/addresses/{w.warehouse_id}"),
        Probe("user.patch", "PATCH", "/api/v1/users/{user_id}", f"/api/v1/users/{w.customer_b2c_id}", {"full_name": "xcut probe"}, customer_scoped=False),
        Probe("user.review_b2b", "POST", "/api/v1/users/{user_id}/review-b2b", f"/api/v1/users/{w.customer_b2c_id}/review-b2b", {"approve": False}, customer_scoped=False),
        Probe("tenant.users", "GET", "/api/v1/tenants/{tenant_id}/users", f"/api/v1/tenants/{w.tenant_id}/users", customer_scoped=False),
        Probe("tenant.patch", "PATCH", "/api/v1/tenants/{tenant_id}", f"/api/v1/tenants/{w.tenant_id}", {"settings": {"announcement_bar": {"text": "xcut probe", "is_active": False}}}, customer_scoped=False),
    ]


LIST_ENDPOINTS_FOR_LEAKS: Sequence[str] = (
    "/api/v1/shipments?size=100",
    "/api/v1/shipments/export/csv",
    "/api/v1/manifests",
    "/api/v1/manifests/eligible-shipments",
    "/api/v1/invoices",
    "/api/v1/remittances",
    "/api/v1/support-tickets",
    "/api/v1/disputes/weight-mismatch",
    "/api/v1/exceptions?service_flow=B2C",
    "/api/v1/wallet/admin/pending-recharges",
    "/api/v1/appointments",
)
"""List screens a NAVIERA owner may open; none may contain a test-tenant identifier.
`/wallet` and `/wallet/transactions` are excluded on purpose: they lazily create the
caller's wallet row, which would be a write into `naviera`."""


async def _snapshot_world(w: World) -> Dict[str, Any]:
    """Mutable fields of every target row (SELECT only), compared before/after the attacks."""
    tenant_id = uuid.UUID(w.tenant_id)
    async with GoldenSessionLocal() as session:
        shipments = (
            await session.exec(
                select(PickupRequest).where(
                    PickupRequest.tenant_id == tenant_id,
                    col(PickupRequest.id).in_([uuid.UUID(w.delivered_id), uuid.UUID(w.open_id)]),
                )
            )
        ).all()
        manifests = (
            await session.exec(
                select(Manifest).where(
                    Manifest.tenant_id == tenant_id,
                    col(Manifest.id).in_([uuid.UUID(w.scheduled_pur_id), uuid.UUID(w.picked_pur_id)]),
                )
            )
        ).all()
        pending = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.tenant_id == tenant_id,
                    WalletTransaction.id == uuid.UUID(w.pending_txn_id),
                )
            )
        ).one()
        dispute = (
            await session.exec(
                select(WeightDispute).where(
                    WeightDispute.tenant_id == tenant_id, WeightDispute.id == uuid.UUID(w.dispute_id)
                )
            )
        ).one()
        ticket = (
            await session.exec(
                select(SupportTicket).where(
                    SupportTicket.tenant_id == tenant_id, SupportTicket.id == uuid.UUID(w.ticket_id)
                )
            )
        ).one()
        address = (
            await session.exec(
                select(Address).where(Address.tenant_id == tenant_id, Address.id == uuid.UUID(w.warehouse_id))
            )
        ).one()
        user = (
            await session.exec(
                select(User).where(User.tenant_id == tenant_id, User.id == uuid.UUID(w.customer_b2c_id))
            )
        ).one()
        tenant_row = (await session.exec(select(Tenant).where(Tenant.id == tenant_id))).one()
        txn_count = (
            await session.execute(
                text("SELECT count(*) FROM wallet_transactions WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        note_count = (
            await session.execute(
                text("SELECT count(*) FROM billing_invoices WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        activity_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM shipment_activities a JOIN pickups p ON p.id = a.pickup_id "
                    "WHERE p.tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
        await session.rollback()
    return {
        "shipments": sorted(
            (str(s.id), _raw(s.status), s.manifest_id and str(s.manifest_id), s.order_reference_id)
            for s in shipments
        ),
        "manifests": sorted((str(m.id), _raw(m.status)) for m in manifests),
        "pending_txn": (_raw(pending.status), pending.utr_number),
        "dispute": (dispute.claim_status, dispute.claim_remarks),
        "ticket": (ticket.status, ticket.updated_at),
        "address": (address.name, address.is_saved),
        "user": (user.full_name, _raw(user.role), _raw(user.service_scope), user.is_active),
        "tenant_settings": tenant_row.settings,
        "tenant_wallet_txns": int(txn_count),
        "tenant_notes": int(note_count),
        "tenant_activities": int(activity_count),
    }


def _assert_denied(probe: Probe, resp: httpx.Response, w: World, who: str) -> None:
    """Outsider response: allowed status and no identifier of the target in the body."""
    assert resp.status_code in probe.allowed, (
        f"[{who}] {probe.name} {probe.method} {probe.path} -> {resp.status_code} "
        f"(expected {sorted(probe.allowed)}): {resp.text[:300]}"
    )
    body = resp.text
    leaked = [m for m in w.leak_markers() if m and m in body]
    assert not leaked, f"[{who}] {probe.name} leaked {leaked} in its error body"


async def _send(client: httpx.AsyncClient, probe: Probe, hdrs: Mapping[str, str]) -> httpx.Response:
    """Sends one probe request."""
    kwargs: Dict[str, Any] = {"headers": dict(hdrs)}
    if probe.body is not None:
        kwargs["json"] = probe.body
    return await client.request(probe.method, probe.path, **kwargs)


def _naviera_probe_user(naviera: Tenant) -> User:
    """
    A NEVER-persisted owner of `naviera` (no session ever adds it). Its id does not exist in
    `user`, so any row a broken guard tried to write for it would fail the FK and roll back.
    """
    return User(
        id=uuid.uuid4(),
        supabase_user_id=f"xcut-probe-{uuid.uuid4()}",
        email="xcut-probe@naviera.invalid",
        role=UserRole.owner,
        service_scope=ServiceScope.BOTH,
        is_active=True,
        tenant_id=naviera.id,
    )


@pytest.fixture(scope="module")
async def j54_world() -> Tuple[World, Mapping[str, Any]]:
    """Builds the J54 targets once for the module."""
    accounts = await load_accounts()
    async with _client() as client:
        world = await _build_world(client, accounts)
    return world, accounts


def _registered_routes() -> FrozenSet[Tuple[str, str]]:
    """(METHOD, path template) of every route mounted on the app."""
    pairs = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                pairs.add((method, route.path))
    return frozenset(pairs)


def test_j54_matrix_routes_are_mounted() -> None:
    """Precondition: a missing route would 404 and fake a pass, so every probed route must exist."""
    dummy = World(*(["00000000-0000-0000-0000-000000000000"] * 17))
    routes = _registered_routes()
    missing = sorted(
        f"{p.method} {p.route}" for p in _probes(dummy) if (p.method, p.route) not in routes
    )
    assert not missing, f"Routes probed by J54 are not mounted (Phase B not merged yet?): {missing}"


async def test_j54a_header_swap_test_token_with_naviera_slug(j54_world: Tuple[World, Mapping[str, Any]]) -> None:
    """A real test-tenant token sent with `X-Tenant-Slug: naviera` is refused on every probe."""
    world, accounts = j54_world
    await _load_second_tenant()
    before = await _snapshot_world(world)
    async with _client() as client:
        for email in (OWNER_EMAIL, CUSTOMER_B2C_EMAIL):
            swapped = dict(headers(accounts, email))
            swapped["X-Tenant-Slug"] = SECOND_TENANT_SLUG
            for probe in _probes(world):
                resp = await _send(client, probe, swapped)
                _assert_denied(probe, resp, world, f"header-swap {email}")
    assert await _snapshot_world(world) == before, "A header-swapped request changed test-tenant data"


async def test_j54b_public_tracking_is_tenant_scoped(j54_world: Tuple[World, Mapping[str, Any]]) -> None:
    """Public tracking of a test-tenant AWB under the `naviera` slug is 404; positive control is 200."""
    world, _ = j54_world
    await _load_second_tenant()
    async with _client() as client:
        for prefix in ("/api/v1/tracking", "/api/v1/shipments/tracking"):
            own = await client.get(f"{prefix}/{world.delivered_awb}", headers={"X-Tenant-Slug": GOLDEN_TENANT_SLUG})
            assert own.status_code == 200, own.text
            other = await client.get(f"{prefix}/{world.delivered_awb}", headers={"X-Tenant-Slug": SECOND_TENANT_SLUG})
            assert other.status_code == 404, (prefix, other.status_code, other.text)
            assert world.delivered_awb not in other.text


async def test_j54c_naviera_principal_by_id_matrix(j54_world: Tuple[World, Mapping[str, Any]]) -> None:
    """
    An owner of `naviera` (in-process, never persisted) reaches the services with
    `tenant_id = naviera`: every by-id probe is 403/404, list screens show no test-tenant
    row, test-tenant data is unchanged and `naviera` row counts are unchanged.
    """
    world, accounts = j54_world
    naviera = await _load_second_tenant()
    probe_user = _naviera_probe_user(naviera)
    naviera_hdrs = {"X-Tenant-Slug": SECOND_TENANT_SLUG, "Authorization": "Bearer xcut-probe"}

    async with _client() as client:
        # Positive controls first: each id is valid and reachable by its rightful owner.
        for probe in _probes(world):
            if probe.method == "GET" and probe.owner_email:
                own = await client.get(probe.path, headers=headers(accounts, probe.owner_email))
                assert own.status_code != 404, f"Positive control {probe.name} -> 404: {own.text[:200]}"

        before_world = await _snapshot_world(world)
        before_naviera = await _second_tenant_row_counts(naviera.id)

        async def _probe_principal() -> User:
            return probe_user

        app.dependency_overrides[get_current_active_user] = _probe_principal
        try:
            for probe in _probes(world):
                resp = await _send(client, probe, naviera_hdrs)
                _assert_denied(probe, resp, world, "naviera-owner")
            for path in LIST_ENDPOINTS_FOR_LEAKS:
                resp = await client.get(path, headers=naviera_hdrs)
                assert resp.status_code < 500, (path, resp.status_code, resp.text[:300])
                leaked = [m for m in world.leak_markers() if m and m in resp.text]
                assert not leaked, f"naviera list {path} leaked test-tenant rows {leaked}"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    assert await _snapshot_world(world) == before_world, "A naviera request changed test-tenant data"
    assert await _second_tenant_row_counts(naviera.id) == before_naviera, "J54 wrote into naviera"


async def test_j54d_cross_merchant_same_tenant(j54_world: Tuple[World, Mapping[str, Any]]) -> None:
    """`customerb2b` cannot read or change `customerb2c`'s rows in the same tenant."""
    world, accounts = j54_world
    before = await _snapshot_world(world)
    b2b = headers(accounts, CUSTOMER_B2B_EMAIL)
    async with _client() as client:
        for probe in _probes(world):
            if not probe.customer_scoped:
                continue
            resp = await _send(client, probe, b2b)
            _assert_denied(probe, resp, world, "cross-merchant")
        bulk = await client.post(
            "/api/v1/exceptions/bulk-action",
            headers=b2b,
            json={"action": NdrAction.REATTEMPT.value, "shipment_ids": [world.open_id]},
        )
        if bulk.status_code == 200:
            assert world.open_id not in [str(x) for x in bulk.json().get("succeeded", [])], bulk.text
        else:
            assert bulk.status_code in DENIED_OR_REJECTED, bulk.text
    assert await _snapshot_world(world) == before, "A cross-merchant request changed customerb2c data"


# =============================================================================
# J55: double submit / races on money endpoints
# =============================================================================


@pytest.fixture(scope="module")
async def j55_ctx() -> Tuple[Mapping[str, Any], str]:
    """Accounts + seeded warehouse, with `customerb2c` funded once."""
    accounts = await load_accounts()
    async with _client() as client:
        await _ensure_funded(client, accounts)
        warehouse_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)
    return accounts, warehouse_id


async def test_j55_book_double_submit_with_idempotency_key(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """A double-clicked booking (same key) creates ONE shipment, ONE SPEND and ONE INVOICE."""
    accounts, warehouse_id = j55_ctx
    cust = headers(accounts, CUSTOMER_B2C_EMAIL)
    payload = _booking_payload(warehouse_id, "J55-BOOK")
    key = _new_key("book")
    balance_before = await get_wallet_balance(accounts[CUSTOMER_B2C_EMAIL]["id"])
    async with _client() as client:
        responses = await _gather(
            client.post("/api/v1/shipments", headers=_with_key(cust, key), json=payload),
            client.post("/api/v1/shipments", headers=_with_key(cust, key), json=payload),
        )
        winner = _keyed_race_winner(responses)
        shipment_id = winner.json()["id"]
        _assert_replay(winner, await client.post("/api/v1/shipments", headers=_with_key(cust, key), json=payload))
        changed = _booking_payload(warehouse_id, "J55-BOOK", weight_kg=EDITED_WEIGHT_KG)
        changed["order_reference_id"] = payload["order_reference_id"]
        _assert_key_mismatch(await client.post("/api/v1/shipments", headers=_with_key(cust, key), json=changed))

    assert await _count_shipments_with_ref(payload["order_reference_id"]) == 1
    assert await _count_txns(shipment_id, WalletTxnType.SPEND) == 1
    assert await _count_notes(shipment_id, InvoiceNoteType.INVOICE) == 1
    bill = await _bill_total(shipment_id)
    assert await _net_debited(shipment_id) == bill
    balance_after = await get_wallet_balance(accounts[CUSTOMER_B2C_EMAIL]["id"])
    assert round(balance_before - balance_after, MONEY_DECIMALS) == bill


async def test_j55_cancel_race_refunds_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two concurrent cancels: one 200, one refused; ONE REFUND and ONE CREDIT_NOTE; net debited 0."""
    accounts, warehouse_id = j55_ctx
    cust = headers(accounts, CUSTOMER_B2C_EMAIL)
    async with _client() as client:
        shipment = await _book(client, accounts, warehouse_id, "J55-CANCEL")
        path = f"/api/v1/shipments/{shipment['id']}/cancel"
        responses = await _gather(client.post(path, headers=cust), client.post(path, headers=cust))
    winner = _one_winner(responses, DUPLICATE_REFUSED)
    assert winner.json()["status"] == PickupStatus.CANCELLED.value
    assert await _count_txns(shipment["id"], WalletTxnType.REFUND) == 1
    assert await _count_notes(shipment["id"], InvoiceNoteType.CREDIT_NOTE) == 1
    assert await _net_debited(shipment["id"]) == 0.0


async def test_j55_settle_cod_race_credits_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two concurrent admin settle-cod calls credit a merchant's delivered COD exactly once (+ key replay)."""
    accounts, warehouse_id = j55_ctx
    admin = headers(accounts, ADMIN_EMAIL)
    user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    settle_url = f"/api/v1/wallet/settle-cod?merchant_user_id={user_id}"
    async with _client() as client:
        shipment = await _book_and_dispatch(client, accounts, warehouse_id, "J55-COD", is_cod=True)
        await _deliver(client, accounts, shipment["id"])
        balance_before = await get_wallet_balance(user_id)
        key = _new_key("settle")
        responses = await _gather(
            client.post(settle_url, headers=_with_key(admin, key)),
            client.post(settle_url, headers=_with_key(admin, key)),
        )
        winner = _keyed_race_winner(responses)
        _assert_replay(winner, await client.post(settle_url, headers=_with_key(admin, key)))
        unkeyed = await _gather(
            client.post(settle_url, headers=admin),
            client.post(settle_url, headers=admin),
        )
    for resp in unkeyed:
        assert resp.status_code in SUCCESS_STATUSES | DUPLICATE_REFUSED, resp.text
        if resp.status_code in SUCCESS_STATUSES:
            assert _money(resp.json().get("settled_amount")) == 0.0, "COD was paid out twice"
    assert await _count_txns(shipment["id"], WalletTxnType.COD_SETTLEMENT) == 1
    credited = round(await get_wallet_balance(user_id) - balance_before, MONEY_DECIMALS)
    assert credited == _money(winner.json()["settled_amount"])
    assert credited > 0.0


async def test_j55_recharge_approve_race_credits_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two admins approve the same UPI recharge at once: credited once (+ key replay and 422)."""
    accounts, _ = j55_ctx
    admin = headers(accounts, ADMIN_EMAIL)
    user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        txn_a = await _pending_recharge(client, accounts, RACE_RECHARGE_INR)
        balance_before = await get_wallet_balance(user_id)
        key = _new_key("approve")
        path_a = f"/api/v1/wallet/recharge/{txn_a}/approve"
        responses = await _gather(
            client.post(path_a, headers=_with_key(admin, key)),
            client.post(path_a, headers=_with_key(admin, key)),
        )
        winner = _keyed_race_winner(responses)
        _assert_replay(winner, await client.post(path_a, headers=_with_key(admin, key)))
        # An un-keyed re-approve of an already COMPLETED recharge is the service's documented
        # idempotent no-op (`WalletService.approve_pending_recharge`): 200, same transaction,
        # and no second credit (the balance check below proves the wallet moved exactly once).
        balance_after_race = await get_wallet_balance(user_id)
        duplicate = await client.post(path_a, headers=admin)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["transaction_id"] == txn_a
        assert duplicate.json()["status"] == WalletTxnStatus.COMPLETED.value
        assert await get_wallet_balance(user_id) == balance_after_race

        txn_b = await _pending_recharge(client, accounts, SECOND_RECHARGE_INR)
        _assert_key_mismatch(await client.post(f"/api/v1/wallet/recharge/{txn_b}/approve", headers=_with_key(admin, key)))

    assert round(await get_wallet_balance(user_id) - balance_before, MONEY_DECIMALS) == RACE_RECHARGE_INR
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        txn = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.tenant_id == tenant_id, WalletTransaction.id == uuid.UUID(txn_a)
                )
            )
        ).one()
        other = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.tenant_id == tenant_id, WalletTransaction.id == uuid.UUID(txn_b)
                )
            )
        ).one()
        await session.rollback()
    assert txn.status == WalletTxnStatus.COMPLETED
    assert other.status == WalletTxnStatus.PENDING, "A reused key must not approve another recharge"


async def test_j55_claim_accept_race_refunds_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two concurrent 'Accept & Refund' on one weight claim: ONE REFUND, ONE CREDIT_NOTE (+ key rules)."""
    accounts, warehouse_id = j55_ctx
    admin = headers(accounts, ADMIN_EMAIL)
    async with _client() as client:
        shipment = await _book_and_dispatch(client, accounts, warehouse_id, "J55-CLAIM")
        await _audit_weight(client, accounts, shipment["id"], MEASURED_WEIGHT_KG)
        await _raise_claim(client, accounts, shipment["tracking_id"])
        dispute_id = await _dispute_id(client, accounts, shipment["tracking_id"])
        refunds_before = await _count_txns(shipment["id"], WalletTxnType.REFUND)
        credit_notes_before = await _count_notes(shipment["id"], InvoiceNoteType.CREDIT_NOTE)
        path = f"/api/v1/disputes/weight-mismatch/{dispute_id}/resolve"
        accept = {"claim_status": WeightDisputeClaimStatus.ACCEPTED.value, "claim_remarks": "Xcut accept"}
        key = _new_key("claim")
        responses = await _gather(
            client.patch(path, headers=_with_key(admin, key), json=accept),
            client.patch(path, headers=_with_key(admin, key), json=accept),
        )
        winner = _keyed_race_winner(responses)
        _assert_replay(winner, await client.patch(path, headers=_with_key(admin, key), json=accept))
        reject = {"claim_status": WeightDisputeClaimStatus.REJECTED.value, "claim_remarks": "Xcut reject"}
        _assert_key_mismatch(await client.patch(path, headers=_with_key(admin, key), json=reject))
        unkeyed = await _gather(
            client.patch(path, headers=admin, json=accept), client.patch(path, headers=admin, json=accept)
        )
    assert all(r.status_code in DUPLICATE_REFUSED for r in unkeyed), _statuses(unkeyed)
    assert await _count_txns(shipment["id"], WalletTxnType.REFUND) == refunds_before + 1
    assert await _count_notes(shipment["id"], InvoiceNoteType.CREDIT_NOTE) == credit_notes_before + 1
    assert await _net_debited(shipment["id"]) == await _bill_total(shipment["id"])


async def test_j55_acknowledge_charges_race_debits_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two concurrent 'Acknowledge & Pay' on one Additional Charges hold: ONE ADDITIONAL_CHARGE row."""
    accounts, warehouse_id = j55_ctx
    cust = headers(accounts, CUSTOMER_B2C_EMAIL)
    async with _client() as client:
        shipment = await _book_and_dispatch(client, accounts, warehouse_id, "J55-ACK")
        await _raise_charge_exception(client, accounts, shipment["id"])
        path = f"/api/v1/exceptions/{shipment['id']}/actions"
        body = {"action": NdrAction.ACKNOWLEDGE_CHARGES.value, "notes": "Xcut ack"}
        key = _new_key("ack")
        responses = await _gather(
            client.post(path, headers=_with_key(cust, key), json=body),
            client.post(path, headers=_with_key(cust, key), json=body),
        )
        winner = _keyed_race_winner(responses)
        _assert_replay(winner, await client.post(path, headers=_with_key(cust, key), json=body))
        _assert_key_mismatch(
            await client.post(path, headers=_with_key(cust, key), json={**body, "notes": "Xcut changed"})
        )
        duplicate = await client.post(path, headers=cust, json=body)
    assert duplicate.status_code in DUPLICATE_REFUSED, duplicate.text
    assert await _count_txns(shipment["id"], WalletTxnType.ADDITIONAL_CHARGE) == 1
    assert await _count_notes(shipment["id"], InvoiceNoteType.DEBIT_NOTE) == 1


async def test_j55_dispatch_race_picks_up_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two riders confirm the same pickup at once: one 200, one refused; ONE IN_TRANSIT transition."""
    accounts, warehouse_id = j55_ctx
    async with _client() as client:
        shipment = await _book(client, accounts, warehouse_id, "J55-DISPATCH")
        pur = await _create_pur(client, accounts, warehouse_id, [shipment["id"]])
        responses = await _gather(
            _dispatch_request(client, accounts, pur["id"], [shipment["id"]]),
            _dispatch_request(client, accounts, pur["id"], [shipment["id"]]),
        )
    winner = _one_winner(responses, DUPLICATE_REFUSED)
    assert winner.json()["status"] == ManifestStatus.PICKED.value
    assert await _count_status_transitions(shipment["id"], PickupStatus.IN_TRANSIT) == 1
    assert await _count_txns(shipment["id"], WalletTxnType.SPEND) == 1
    assert await _net_debited(shipment["id"]) == await _bill_total(shipment["id"])


async def test_j55_reprice_apply_race_bills_delta_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two identical admin weight edits at once: the delta is billed ONCE (one DEBIT_NOTE, one priced adjustment)."""
    accounts, warehouse_id = j55_ctx
    admin = headers(accounts, ADMIN_EMAIL)
    async with _client() as client:
        shipment = await _book(client, accounts, warehouse_id, "J55-REPRICE")
        package = dict(shipment["packages"][0])
        edit = {
            "comment": "Xcut weight correction",
            "packages": [
                {
                    "id": package["id"],
                    "length": package["length"],
                    "breadth": package["breadth"],
                    "height": package["height"],
                    "dimension_unit": package["dimension_unit"],
                    "weight": EDITED_WEIGHT_KG,
                    "weight_unit": package["weight_unit"],
                    "box_count": package["box_count"],
                    "description": package.get("description"),
                }
            ],
        }
        path = f"/api/v1/shipments/{shipment['id']}"
        responses = await _gather(
            client.patch(path, headers=admin, json=edit), client.patch(path, headers=admin, json=edit)
        )
    assert all(r.status_code in SUCCESS_STATUSES | DUPLICATE_REFUSED for r in responses), _statuses(responses)
    assert any(r.status_code in SUCCESS_STATUSES for r in responses), [r.text for r in responses]
    bill = await _bill_total(shipment["id"])
    assert bill > _money(shipment["payment_details"]["total_logistics_cost"])
    assert await _net_debited(shipment["id"]) == bill
    assert await _count_notes(shipment["id"], InvoiceNoteType.DEBIT_NOTE) == 1
    assert (
        await _count_pickup_rows("shipment_charge_adjustments", shipment["id"], "AND new_total <> old_total")
        == 1
    )


async def test_j55_measurement_race_records_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two concurrent identical hub measurements with the same key: ONE measurement, ONE adjustment, ONE debit."""
    accounts, warehouse_id = j55_ctx
    ops = headers(accounts, OPERATIONS_EMAIL)
    async with _client() as client:
        shipment = await _book_and_dispatch(client, accounts, warehouse_id, "J55-MEASURE")
        path = f"/api/v1/shipments/{shipment['id']}/measurements"
        body = {"source": "HUB", "weight_kg": MEASURED_WEIGHT_KG, "remark": "Xcut DWS scan"}
        key = _new_key("measure")
        responses = await _gather(
            client.post(path, headers=_with_key(ops, key), json=body),
            client.post(path, headers=_with_key(ops, key), json=body),
        )
        winner = _keyed_race_winner(responses)
        _assert_replay(winner, await client.post(path, headers=_with_key(ops, key), json=body))
        _assert_key_mismatch(
            await client.post(path, headers=_with_key(ops, key), json={**body, "weight_kg": OTHER_MEASURED_WEIGHT_KG})
        )
    assert await _count_pickup_rows("shipment_measurements", shipment["id"]) == 1
    assert await _count_pickup_rows("shipment_measurements", shipment["id"], "AND is_active") == 1
    assert await _count_pickup_rows("shipment_charge_adjustments", shipment["id"]) == 1
    assert await _count_txns(shipment["id"], WalletTxnType.WEIGHT_AUDIT_DEBIT) == 1
    assert await _count_notes(shipment["id"], InvoiceNoteType.DEBIT_NOTE) == 1
    assert await _net_debited(shipment["id"]) == await _bill_total(shipment["id"])

async def test_j55_manifest_cancel_race_cancels_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """Two concurrent manifest cancels: ONE canceled manifest, ONE 409 replay response."""
    accounts, warehouse_id = j55_ctx
    cust = headers(accounts, CUSTOMER_B2C_EMAIL)
    async with _client() as client:
        shipment = await _book(client, accounts, warehouse_id, "J55-MAN-CAN")
        # A B2C parcel goes on a B2C pickup request (the API defaults service_flow to B2B).
        pur_id = (await _create_pur(client, accounts, warehouse_id, [shipment["id"]]))["id"]

        path = f"/api/v1/manifests/{pur_id}/cancel"
        key = _new_key("manifest_cancel")
        responses = await _gather(
            client.post(path, headers=_with_key(cust, key)),
            client.post(path, headers=_with_key(cust, key)),
        )
        winner = _keyed_race_winner(responses)
        _assert_replay(winner, await client.post(path, headers=_with_key(cust, key)))
        
        duplicate = await client.post(path, headers=cust)
        assert duplicate.status_code in DUPLICATE_REFUSED, duplicate.text


async def test_j55_resolve_exception_race_resolves_once(j55_ctx: Tuple[Mapping[str, Any], str]) -> None:
    """
    Two concurrent REATTEMPT actions with one Idempotency-Key on a delivery NDR: the hold is
    released once (one NDR action activity, one attempt), the replay is identical, and an
    un-keyed repeat is refused because the parcel is no longer on hold.
    """
    accounts, warehouse_id = j55_ctx
    cust = headers(accounts, CUSTOMER_B2C_EMAIL)
    async with _client() as client:
        shipment = await _book_and_dispatch(client, accounts, warehouse_id, "J55-RESOLVE")
        sid = shipment["id"]
        hold = await client.patch(
            f"/api/v1/shipments/{sid}",
            headers=headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.CONSIGNEE_UNAVAILABLE.value,
                "ndr_remark": "J55 consignee unavailable",
            },
        )
        assert hold.status_code == 200, hold.text
        assert hold.json()["ndr_attempt_count"] == 1

        path = f"/api/v1/exceptions/{sid}/actions"
        key = _new_key("resolve_exception")
        body = {"action": NdrAction.REATTEMPT.value}
        responses = await _gather(
            client.post(path, headers=_with_key(cust, key), json=body),
            client.post(path, headers=_with_key(cust, key), json=body),
        )
        winner = _keyed_race_winner(responses)
        assert winner.json()["status"] != PickupStatus.EXCEPTION.value
        _assert_replay(winner, await client.post(path, headers=_with_key(cust, key), json=body))

        duplicate = await client.post(path, headers=cust, json=body)
        assert duplicate.status_code in DUPLICATE_REFUSED, duplicate.text

    assert await _count_ndr_actions(sid, NdrAction.REATTEMPT) == 1
