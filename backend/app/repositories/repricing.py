"""
Data access for Phase B re-pricing: shipments under row lock, measurements,
charge adjustments, shipment wallet ledger rows and idempotency keys.

Every method takes `tenant_id` and filters on it (AGENTS §5, plan §2.0).
Spring analogy: a `@Repository` (JpaRepository + a few `@Query` methods,
including a `@Lock(PESSIMISTIC_WRITE)` finder).
"""

import uuid
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import update
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.delhivery_modules import BillingInvoice, InvoiceNoteType
from app.models.pickups import Address, PickupRequest
from app.models.repricing import (
    IdempotencyKey,
    ShipmentChargeAdjustment,
    ShipmentMeasurement,
)
from app.models.tenants import User
from app.models.wallet import WalletTransaction, WalletTxnStatus, WalletTxnType


@dataclass(frozen=True)
class AdjustmentJoinRow:
    """One adjustment with its GST note number/type and the actor's email (charges history)."""

    adjustment: ShipmentChargeAdjustment
    note_number: Optional[str]
    note_type: Optional[str]
    actor_email: Optional[str]


class RepricingRepository:
    """Tenant-scoped queries used by `RepricingService`. Never commits."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------- shipments

    async def get_shipment(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID, *, for_update: bool = False
    ) -> Optional[PickupRequest]:
        """
        Loads a shipment with addresses, packages, documents and payment details.

        Relations use `selectinload` (separate SELECTs), so `FOR UPDATE` applies to the
        `pickups` row only and never to the nullable side of an outer join.

        Args:
            shipment_id: The shipment.
            tenant_id: Owning tenant (isolation filter).
            for_update: Lock the shipment row until the transaction ends.

        Returns:
            The shipment, or None when it does not exist in this tenant.
        """
        query = (
            select(PickupRequest)
            .where(PickupRequest.id == shipment_id, PickupRequest.tenant_id == tenant_id)
            .options(
                selectinload(PickupRequest.pickup_address),  # type: ignore[arg-type]
                selectinload(PickupRequest.delivery_address),  # type: ignore[arg-type]
                selectinload(PickupRequest.packages),  # type: ignore[arg-type]
                selectinload(PickupRequest.documents),  # type: ignore[arg-type]
                selectinload(PickupRequest.payment_details),  # type: ignore[arg-type]
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.exec(query)
        return result.first()

    async def get_address_pincode(
        self, address_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[str]:
        """Pincode of a tenant address (None when it is not in this tenant)."""
        result = await self.session.exec(
            select(Address.pincode).where(Address.id == address_id, Address.tenant_id == tenant_id)
        )
        return result.first()

    async def find_shipment_by_carrier_awb(
        self, tenant_id: uuid.UUID, carrier_awb: str, *, exclude_shipment_id: uuid.UUID
    ) -> Optional[PickupRequest]:
        """Another shipment in this tenant that already carries `carrier_awb`, if any."""
        result = await self.session.exec(
            select(PickupRequest).where(
                PickupRequest.tenant_id == tenant_id,
                PickupRequest.carrier_awb == carrier_awb,
                PickupRequest.id != exclude_shipment_id,
            )
        )
        return result.first()

    # ---------------------------------------------------------- measurements

    async def get_active_measurement(
        self, pickup_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[ShipmentMeasurement]:
        """The active (billing-basis) measurement of a shipment, if any."""
        result = await self.session.exec(
            select(ShipmentMeasurement).where(
                ShipmentMeasurement.pickup_id == pickup_id,
                ShipmentMeasurement.tenant_id == tenant_id,
                col(ShipmentMeasurement.is_active).is_(True),
            )
        )
        return result.first()

    async def deactivate_measurements(self, pickup_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Marks every measurement of a shipment inactive (before a new one becomes active)."""
        await self.session.exec(  # type: ignore[call-overload]
            update(ShipmentMeasurement)
            .where(
                col(ShipmentMeasurement.pickup_id) == pickup_id,
                col(ShipmentMeasurement.tenant_id) == tenant_id,
                col(ShipmentMeasurement.is_active).is_(True),
            )
            .values(is_active=False)
        )

    async def add_measurement(self, measurement: ShipmentMeasurement) -> ShipmentMeasurement:
        """Inserts a measurement row and flushes it."""
        self.session.add(measurement)
        await self.session.flush()
        return measurement

    # ----------------------------------------------------------- adjustments

    async def add_adjustment(self, adjustment: ShipmentChargeAdjustment) -> ShipmentChargeAdjustment:
        """Inserts a charge adjustment row and flushes it."""
        self.session.add(adjustment)
        await self.session.flush()
        return adjustment

    async def get_adjustment_by_idempotency_key(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> Optional[ShipmentChargeAdjustment]:
        """The adjustment already written under this key in this tenant, if any."""
        result = await self.session.exec(
            select(ShipmentChargeAdjustment).where(
                ShipmentChargeAdjustment.tenant_id == tenant_id,
                ShipmentChargeAdjustment.idempotency_key == idempotency_key,
            )
        )
        return result.first()

    async def list_adjustments(
        self, pickup_id: uuid.UUID, tenant_id: uuid.UUID, *, newest_first: bool = True
    ) -> List[ShipmentChargeAdjustment]:
        """All adjustments of a shipment."""
        order = col(ShipmentChargeAdjustment.created_at)
        result = await self.session.exec(
            select(ShipmentChargeAdjustment)
            .where(
                ShipmentChargeAdjustment.pickup_id == pickup_id,
                ShipmentChargeAdjustment.tenant_id == tenant_id,
            )
            .order_by(order.desc() if newest_first else order.asc())
        )
        return list(result.all())

    async def list_adjustments_joined(
        self, pickup_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[AdjustmentJoinRow]:
        """Adjustments oldest first, with the GST note number/type and actor email joined in."""
        query = (
            select(
                ShipmentChargeAdjustment,
                BillingInvoice.invoice_number,
                BillingInvoice.note_type,
                User.email,
            )
            .join(
                BillingInvoice,
                (col(BillingInvoice.id) == col(ShipmentChargeAdjustment.billing_invoice_id))
                & (col(BillingInvoice.tenant_id) == tenant_id),
                isouter=True,
            )
            .join(User, col(User.id) == col(ShipmentChargeAdjustment.actor_user_id), isouter=True)
            .where(
                ShipmentChargeAdjustment.pickup_id == pickup_id,
                ShipmentChargeAdjustment.tenant_id == tenant_id,
            )
            .order_by(col(ShipmentChargeAdjustment.created_at).asc())
        )
        result = await self.session.exec(query)
        return [
            AdjustmentJoinRow(adjustment=row[0], note_number=row[1], note_type=row[2], actor_email=row[3])
            for row in result.all()
        ]

    # ---------------------------------------------------------------- wallet

    async def list_shipment_wallet_txns(
        self, pickup_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[WalletTransaction]:
        """COMPLETED wallet ledger rows of one shipment, oldest first."""
        result = await self.session.exec(
            select(WalletTransaction)
            .where(
                WalletTransaction.shipment_id == pickup_id,
                WalletTransaction.tenant_id == tenant_id,
                WalletTransaction.status == WalletTxnStatus.COMPLETED,
            )
            .order_by(col(WalletTransaction.created_at).asc())
        )
        return list(result.all())

    async def add_wallet_txn(self, txn: WalletTransaction) -> WalletTransaction:
        """Inserts a wallet ledger row and flushes it."""
        self.session.add(txn)
        await self.session.flush()
        return txn

    async def has_wallet_txn_type(
        self, pickup_id: uuid.UUID, tenant_id: uuid.UUID, txn_type: WalletTxnType
    ) -> bool:
        """True when the shipment already has a COMPLETED ledger row of this type."""
        result = await self.session.exec(
            select(WalletTransaction.id).where(
                WalletTransaction.shipment_id == pickup_id,
                WalletTransaction.tenant_id == tenant_id,
                WalletTransaction.txn_type == txn_type,
                WalletTransaction.status == WalletTxnStatus.COMPLETED,
            )
        )
        return result.first() is not None

    async def has_shipment_invoice(self, pickup_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        """True when the shipment already has its GST INVOICE in this tenant."""
        result = await self.session.exec(
            select(BillingInvoice.id).where(
                BillingInvoice.tenant_id == tenant_id,
                BillingInvoice.shipment_id == pickup_id,
                BillingInvoice.note_type == InvoiceNoteType.INVOICE.value,
            )
        )
        return result.first() is not None


class IdempotencyRepository:
    """Tenant + user scoped access to `idempotency_keys` (H-4)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, endpoint: str, key: str
    ) -> Optional[IdempotencyKey]:
        """The stored claim/response for this scope, if any."""
        result = await self.session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == tenant_id,
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.key == key,
            )
        )
        return result.first()

    async def add(self, row: IdempotencyKey) -> IdempotencyKey:
        """Inserts a claim row and flushes it (raises IntegrityError on a concurrent duplicate)."""
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, *, tenant_id: uuid.UUID, row_id: uuid.UUID) -> None:
        """Removes a claim (used when the guarded request failed, so a retry may run)."""
        row = await self.session.get(IdempotencyKey, row_id)
        if row is not None and row.tenant_id == tenant_id:
            await self.session.delete(row)
            await self.session.flush()
