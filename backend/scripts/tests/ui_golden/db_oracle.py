"""
Read-only database oracle for UI journeys (ship-readiness plan E3).

After a UI action, the journey asks the oracle what the database now holds
(status, wallet balance, ledger rows, GST documents) and compares it with the
screen. Every query:
- runs inside a transaction marked `READ ONLY` (Postgres rejects any write);
- is filtered by the guarded `logismart-test` tenant id (AGENTS §5);
- is rolled back at the end (nothing is ever committed).

Spring analogy: a `@Transactional(readOnly = true)` test DAO bound to one tenant.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, AsyncIterator, List, Optional, Sequence
from uuid import UUID

from sqlmodel import col, select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.delhivery_modules import (
    BillingInvoice,
    CodRemittance,
    InvoiceNoteType,
    WeightDispute,
)
from app.models.pickups import PaymentDetails, PickupRequest
from app.models.tenants import User
from app.models.wallet import UserWallet, WalletTransaction, WalletTxnStatus

from .money import to_paisa

READ_ONLY_STATEMENT = "SET TRANSACTION READ ONLY"


class OracleError(AssertionError):
    """Raised when the oracle cannot find a row the journey expects."""


@dataclass(frozen=True)
class ShipmentSnapshot:
    """The money-relevant facts of one shipment, as stored."""

    shipment_id: UUID
    tracking_id: str
    status: str
    total_logistics_cost: Decimal
    cod_amount: Decimal
    chargeable_weight: Decimal
    pickup_address_id: Optional[UUID]


@dataclass(frozen=True)
class GstDocument:
    """One INVOICE / CREDIT_NOTE / DEBIT_NOTE row."""

    invoice_number: str
    note_type: str
    total_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal


class DbOracle:
    """Tenant-bound, read-only lookups used by UI assertions."""

    def __init__(self, tenant_id: UUID) -> None:
        """
        Args:
            tenant_id: Id of the already-guarded test tenant (from `golden_env.get_tenant_id`).
        """
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> UUID:
        """The tenant every query is filtered by."""
        return self._tenant_id

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """
        Yields a session inside a READ ONLY transaction and always rolls it back. Loaded rows
        are expunged first, so callers can still read their attributes after the block (a
        plain rollback would expire them and raise DetachedInstanceError).
        """
        async with AsyncSessionLocal() as session:
            await session.exec(text(READ_ONLY_STATEMENT))
            try:
                yield session
            finally:
                session.expunge_all()
                await session.rollback()

    # --- Users --------------------------------------------------------------

    async def user_id(self, email: str) -> UUID:
        """
        Returns the id of the test-tenant user with this email.

        Raises:
            OracleError: When no such user exists in the test tenant.
        """
        async with self._session() as session:
            user = (
                await session.exec(
                    select(User).where(User.email == email, User.tenant_id == self._tenant_id)
                )
            ).first()
        if user is None:
            raise OracleError(f"No user {email!r}")
        return user.id

    # --- Shipments ----------------------------------------------------------

    async def shipment(self, tracking_id: str) -> ShipmentSnapshot:
        """
        Returns the stored money facts of the shipment with this AWB/LR.

        Raises:
            OracleError: When the AWB does not exist in the test tenant.
        """
        async with self._session() as session:
            row = (
                await session.exec(
                    select(PickupRequest, PaymentDetails)
                    .join(PaymentDetails, PaymentDetails.pickup_id == PickupRequest.id)
                    .where(
                        PickupRequest.tenant_id == self._tenant_id,
                        PickupRequest.tracking_id == tracking_id,
                    )
                )
            ).first()
        if row is None:
            raise OracleError(f"No shipment {tracking_id!r} in tenant {self._tenant_id}")
        pickup, payment = row
        return ShipmentSnapshot(
            shipment_id=pickup.id,
            tracking_id=tracking_id,
            status=_enum_value(pickup.status),
            total_logistics_cost=to_paisa(payment.total_logistics_cost or 0),
            cod_amount=to_paisa(payment.cod_amount or 0),
            chargeable_weight=to_paisa(payment.chargeable_weight or 0),
            pickup_address_id=pickup.pickup_address_id,
        )

    # --- Wallet -------------------------------------------------------------

    async def wallet_balance(self, user_id: UUID) -> Decimal:
        """Returns `user_wallets.balance` for one user (₹0.00 when there is no wallet yet)."""
        async with self._session() as session:
            wallet = (
                await session.exec(
                    select(UserWallet).where(
                        UserWallet.tenant_id == self._tenant_id,
                        UserWallet.user_id == user_id,
                    )
                )
            ).first()
        return to_paisa(wallet.balance if wallet else 0)

    async def wallet_transactions(
        self, shipment_id: UUID, txn_types: Optional[Sequence[str]] = None
    ) -> List[WalletTransaction]:
        """Returns COMPLETED ledger rows of one shipment, oldest first (optionally by type)."""
        async with self._session() as session:
            stmt = select(WalletTransaction).where(
                WalletTransaction.tenant_id == self._tenant_id,
                WalletTransaction.shipment_id == shipment_id,
                WalletTransaction.status == WalletTxnStatus.COMPLETED,
            )
            if txn_types:
                stmt = stmt.where(col(WalletTransaction.txn_type).in_(list(txn_types)))
            rows = (await session.exec(stmt.order_by(WalletTransaction.created_at))).all()
        return list(rows)

    # --- GST documents ------------------------------------------------------

    async def gst_documents(self, shipment_id: UUID) -> List[GstDocument]:
        """Returns every INVOICE / CREDIT_NOTE / DEBIT_NOTE of one shipment, oldest first."""
        async with self._session() as session:
            rows = (
                await session.exec(
                    select(BillingInvoice)
                    .where(
                        BillingInvoice.tenant_id == self._tenant_id,
                        BillingInvoice.shipment_id == shipment_id,
                    )
                    .order_by(BillingInvoice.created_at)
                )
            ).all()
        return [_to_gst_document(r) for r in rows]

    async def bill_from_documents(self, shipment_id: UUID) -> Decimal:
        """Returns INVOICE + DEBIT_NOTE - CREDIT_NOTE for one shipment (plan §2.0 'the bill')."""
        total = Decimal("0.00")
        for doc in await self.gst_documents(shipment_id):
            if doc.note_type == InvoiceNoteType.CREDIT_NOTE.value:
                total -= doc.total_amount
            else:
                total += doc.total_amount
        return to_paisa(total)

    # --- Weight disputes and remittances ------------------------------------

    async def weight_dispute(self, tracking_id: str) -> WeightDispute:
        """Returns the newest weight-dispute row for this AWB."""
        async with self._session() as session:
            row = (
                await session.exec(
                    select(WeightDispute)
                    .where(
                        WeightDispute.tenant_id == self._tenant_id,
                        WeightDispute.tracking_id == tracking_id,
                    )
                    .order_by(col(WeightDispute.raised_at).desc())
                )
            ).first()
        if row is None:
            raise OracleError(f"No weight dispute for {tracking_id!r}")
        return row

    async def remittance(self, remittance_number: str) -> CodRemittance:
        """Returns one COD remittance batch by its number."""
        async with self._session() as session:
            row = (
                await session.exec(
                    select(CodRemittance).where(
                        CodRemittance.tenant_id == self._tenant_id,
                        CodRemittance.remittance_number == remittance_number,
                    )
                )
            ).first()
        if row is None:
            raise OracleError(f"No remittance {remittance_number!r}")
        return row


def _enum_value(value: Any) -> str:
    """Returns `.value` for enum members and `str(value)` otherwise."""
    return str(getattr(value, "value", value))


def _to_gst_document(row: BillingInvoice) -> GstDocument:
    """Maps one `billing_invoices` row to the immutable DTO."""
    return GstDocument(
        invoice_number=row.invoice_number,
        note_type=row.note_type,
        total_amount=to_paisa(row.total_amount or 0),
        cgst_amount=to_paisa(row.cgst_amount or 0),
        sgst_amount=to_paisa(row.sgst_amount or 0),
        igst_amount=to_paisa(row.igst_amount or 0),
    )
