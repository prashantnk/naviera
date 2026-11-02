import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Set, Tuple

import sqlalchemy as sa
from sqlalchemy import ColumnElement, and_, case, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.delhivery_modules import BillingInvoice, CodRemittance
from app.models.manifests import Manifest
from app.models.pickups import (
    CodRemittanceStatus,
    FreightPaymentMode,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
)
from app.models.repricing import ShipmentMeasurement
from app.models.tenants import User
from app.models.wallet import (
    UserWallet,
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
    _utc_now_naive,
)
from app.services.cod_payout import BILLING_CHANNEL_BREAKDOWN_KEY

WALLET_DEBIT_TXN_TYPES = (
    WalletTxnType.SPEND.value,
    WalletTxnType.WEIGHT_AUDIT_DEBIT.value,
    WalletTxnType.RTO_FREIGHT.value,
    WalletTxnType.FREIGHT_COLLECTION.value,
    WalletTxnType.ADDITIONAL_CHARGE.value,
)
"""Ledger entries that count towards a wallet's total spend."""
PASSBOOK_SPEND_TXN_TYPES = tuple(
    txn_type.value for txn_type in WalletTxnType if txn_type != WalletTxnType.RECHARGE
)
"""A-16: the Transactions tab lists every non-recharge ledger type (incl. RTO freight)."""
UNCONFIRMED_INTENT_VISIBLE_FOR = timedelta(days=3)
"""A-15: a QR intent without "I have paid" stays listed (with "Enter UTR") this long."""


class WalletRepository:
    """
    Data Access Object (DAO) for UserWallet and WalletTransaction.
    Enforces strict multi-tenant isolation ('WHERE tenant_id = :tenant_id') and
    PostgreSQL row-level locking ('SELECT ... FOR UPDATE') during balance mutations.
    Spring Boot Equivalent: '@Repository interface WalletRepository extends JpaRepository<UserWallet, UUID>'
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_tenant_user(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        user_email: Optional[str] = None,
    ) -> Optional[User]:
        """Resolves a tenant user by UUID or case-insensitive email (strict tenant isolation)."""
        if user_id is not None:
            query = select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
            )
            result = await self.session.exec(query)
            return result.first()
        cleaned_email = (user_email or "").strip().lower()
        if not cleaned_email:
            return None
        query = select(User).where(
            User.tenant_id == tenant_id,
            func.lower(User.email) == cleaned_email,
        )
        result = await self.session.exec(query)
        return result.first()

    async def get_wallet(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        for_update: bool = False,
    ) -> Optional[UserWallet]:
        query = select(UserWallet).where(
            UserWallet.user_id == user_id,
            UserWallet.tenant_id == tenant_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.exec(query)
        return result.first()

    async def get_or_create_wallet(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        for_update: bool = False,
    ) -> UserWallet:
        wallet = await self.get_wallet(
            user_id=user_id, tenant_id=tenant_id, for_update=for_update
        )
        if wallet is not None:
            return wallet

        wallet = UserWallet(
            user_id=user_id,
            tenant_id=tenant_id,
            balance=0.0,
            updated_at=_utc_now_naive(),
        )
        self.session.add(wallet)
        await self.session.flush()
        if for_update:
            wallet = await self.get_wallet(
                user_id=user_id, tenant_id=tenant_id, for_update=True
            ) or wallet
        return wallet

    async def get_transaction_by_id(
        self, txn_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[WalletTransaction]:
        query = select(WalletTransaction).where(
            WalletTransaction.id == txn_id,
            WalletTransaction.tenant_id == tenant_id,
        )
        result = await self.session.exec(query)
        return result.first()

    async def get_transaction_by_shipment_id(
        self,
        shipment_id: uuid.UUID,
        tenant_id: uuid.UUID,
        txn_type: Optional[WalletTxnType] = None,
    ) -> Optional[WalletTransaction]:
        filters = [
            WalletTransaction.shipment_id == shipment_id,
            WalletTransaction.tenant_id == tenant_id,
        ]
        if txn_type is not None:
            filters.append(WalletTransaction.txn_type == txn_type.value)
        query = (
            select(WalletTransaction)
            .where(*filters)
            .order_by(WalletTransaction.created_at.desc())
        )
        result = await self.session.exec(query)
        return result.first()

    async def get_transactions_by_shipment_id(
        self,
        shipment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> List[WalletTransaction]:
        """
        Fetches all COMPLETED wallet transactions associated with a specific shipment
        to compute exact net debits/refunds.
        """
        query = (
            select(WalletTransaction)
            .where(
                WalletTransaction.shipment_id == shipment_id,
                WalletTransaction.tenant_id == tenant_id,
                WalletTransaction.status == WalletTxnStatus.COMPLETED,
            )
            .order_by(WalletTransaction.created_at.asc())
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def get_transaction_by_utr(
        self, utr_number: str
    ) -> Optional[WalletTransaction]:
        """
        Checks if a 12-digit NPCI bank UPI UTR has already been redeemed anywhere in the ledger.
        Global check across all tenants because a single real-world bank transfer UTR cannot
        be claimed twice across multiple accounts or tenants.
        """
        query = select(WalletTransaction).where(
            WalletTransaction.utr_number == utr_number
        )
        result = await self.session.exec(query)
        return result.first()

    async def create_transaction(
        self, txn: WalletTransaction
    ) -> WalletTransaction:
        self.session.add(txn)
        await self.session.flush()
        return txn

    async def list_transactions(
        self,
        user_id: Optional[uuid.UUID],
        tenant_id: uuid.UUID,
        tab: str = "all",
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[WalletTransaction], int]:
        """
        Paginated ledger rows with `user_email` attached.

        Args:
            user_id: Restrict to one user's wallet, or None for every user in the tenant
                (tenant-wide ledger for Owner / Admin / Read-Only staff).
        """
        filters = [WalletTransaction.tenant_id == tenant_id]
        if user_id is not None:
            filters.append(WalletTransaction.user_id == user_id)

        normalized_tab = (tab or "all").lower().strip()
        if normalized_tab == "recharges":
            filters.append(WalletTransaction.txn_type == WalletTxnType.RECHARGE.value)
            filters.append(self._visible_recharge_clause())
        elif normalized_tab in ("spends", "transactions"):
            filters.append(WalletTransaction.status == WalletTxnStatus.COMPLETED)
            filters.append(WalletTransaction.txn_type.in_(PASSBOOK_SPEND_TXN_TYPES))
        else:
            filters.append(
                or_(
                    and_(
                        WalletTransaction.txn_type != WalletTxnType.RECHARGE.value,
                        WalletTransaction.status == WalletTxnStatus.COMPLETED,
                    ),
                    and_(
                        WalletTransaction.txn_type == WalletTxnType.RECHARGE.value,
                        self._visible_recharge_clause(),
                    ),
                )
            )

        count_query = select(func.count()).select_from(WalletTransaction).where(*filters)
        total_res = await self.session.exec(count_query)
        total = int(total_res.one() or 0)

        offset = (max(page, 1) - 1) * size
        data_query = (
            select(WalletTransaction, User.email)
            .outerjoin(User, WalletTransaction.user_id == User.id)
            .where(*filters)
            .order_by(WalletTransaction.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        rows = await self.session.exec(data_query)
        return self._attach_user_emails(rows.all()), total

    @staticmethod
    def _visible_recharge_clause() -> ColumnElement[bool]:
        """
        Recharge rows the passbook shows (A-15): completed ones, ones awaiting admin approval,
        REJECTED ones (with the admin's reason in `remarks`), and recent QR intents the user
        never confirmed, so they can still enter the UTR instead of losing the payment.
        """
        intent_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - UNCONFIRMED_INTENT_VISIBLE_FOR
        return or_(
            WalletTransaction.status == WalletTxnStatus.COMPLETED,
            WalletTransaction.status == WalletTxnStatus.FAILED,
            and_(
                WalletTransaction.status == WalletTxnStatus.PENDING,
                or_(
                    WalletTransaction.utr_number.is_not(None),  # type: ignore
                    WalletTransaction.created_at >= intent_cutoff,
                ),
            ),
        )

    @staticmethod
    def _attach_user_emails(rows: Any) -> List[WalletTransaction]:
        """Attaches the owning user's email as a transient `user_email` attribute."""
        items: List[WalletTransaction] = []
        for txn, email in rows:
            object.__setattr__(txn, "user_email", email)
            items.append(txn)
        return items

    async def list_pending_recharges_for_tenant(
        self, tenant_id: uuid.UUID
    ) -> List[WalletTransaction]:
        """
        Fetches all submitted 'I Have Paid' PENDING recharge requests across the tenant
        for the Admin Approval Queue, attaching `user_email` to each transaction.
        """
        query = (
            select(WalletTransaction, User.email)
            .join(User, WalletTransaction.user_id == User.id)
            .where(
                WalletTransaction.tenant_id == tenant_id,
                WalletTransaction.txn_type == WalletTxnType.RECHARGE.value,
                WalletTransaction.status == WalletTxnStatus.PENDING,
                WalletTransaction.utr_number.is_not(None),  # type: ignore
            )
            .order_by(WalletTransaction.created_at.desc())
        )
        res = await self.session.exec(query)
        items: List[WalletTransaction] = []
        for txn, email in res.all():
            object.__setattr__(txn, "user_email", email)
            items.append(txn)
        return items

    async def list_all_user_transactions(
        self, user_id: Optional[uuid.UUID], tenant_id: uuid.UUID
    ) -> List[WalletTransaction]:
        """COMPLETED ledger rows (one user, or the whole tenant when `user_id` is None)."""
        filters = [
            WalletTransaction.tenant_id == tenant_id,
            WalletTransaction.status == WalletTxnStatus.COMPLETED,
        ]
        if user_id is not None:
            filters.append(WalletTransaction.user_id == user_id)
        query = (
            select(WalletTransaction, User.email)
            .outerjoin(User, WalletTransaction.user_id == User.id)
            .where(*filters)
            .order_by(WalletTransaction.created_at.desc())
        )
        rows = await self.session.exec(query)
        return self._attach_user_emails(rows.all())

    async def get_wallet_summary(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict:
        """
        Passbook totals in a single round trip: conditional SUMs over the
        ledger plus a scalar sub-select for collectible (delivered, unremitted) COD.
        """
        amount = col(WalletTransaction.amount)
        txn_type = col(WalletTransaction.txn_type)
        is_completed = col(WalletTransaction.status) == WalletTxnStatus.COMPLETED.value

        def _sum_where(condition: ColumnElement[bool]) -> Any:
            return func.coalesce(func.sum(case((condition, amount), else_=0.0)), 0.0)

        collectible_cod = (
            select(func.coalesce(func.sum(self._cod_payout_expression()), 0.0))
            .join(PickupRequest, PaymentDetails.pickup_id == PickupRequest.id)
            .where(
                PickupRequest.tenant_id == tenant_id,
                PickupRequest.created_by_user_id == user_id,
                PickupRequest.status == PickupStatus.COMPLETED,
                PaymentDetails.is_cod == True,  # noqa: E712
                PaymentDetails.cod_remittance_status != CodRemittanceStatus.REMITTED,
                ~self._went_through_rto_clause(),
            )
            .scalar_subquery()
        )
        statement = select(
            _sum_where(and_(is_completed, txn_type == WalletTxnType.RECHARGE.value)),
            _sum_where(and_(is_completed, txn_type.in_(WALLET_DEBIT_TXN_TYPES))),
            _sum_where(and_(is_completed, txn_type == WalletTxnType.REFUND.value)),
            _sum_where(
                and_(
                    col(WalletTransaction.status) == WalletTxnStatus.PENDING.value,
                    txn_type == WalletTxnType.RECHARGE.value,
                    col(WalletTransaction.utr_number).is_not(None),
                )
            ),
            collectible_cod,
        ).where(
            WalletTransaction.tenant_id == tenant_id,
            WalletTransaction.user_id == user_id,
        )
        recharged, spent, refunded, pending, cod = (await self.session.exec(statement)).one()
        return {
            "total_recharged": round(float(recharged or 0.0), 2),
            "pending_recharge": round(float(pending or 0.0), 2),
            "total_spent": round(float(spent or 0.0), 2),
            "total_refunded": round(float(refunded or 0.0), 2),
            "collectible_cod": round(float(cod or 0.0), 2),
        }

    async def get_unsettled_completed_cod_shipments(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[PickupRequest]:
        """
        COMPLETED COD shipments that were actually delivered to the consignee
        and not yet remitted. Shipments that ever entered RTO_INITIATED reached
        COMPLETED by returning to the merchant, so no cash was collected.
        """
        query = (
            select(PickupRequest)
            .join(PaymentDetails, PaymentDetails.pickup_id == PickupRequest.id)
            .where(
                PickupRequest.tenant_id == tenant_id,
                PickupRequest.created_by_user_id == user_id,
                PickupRequest.status == PickupStatus.COMPLETED,
                PaymentDetails.is_cod == True,  # noqa: E712
                PaymentDetails.cod_remittance_status != CodRemittanceStatus.REMITTED,
                ~self._went_through_rto_clause(),
            )
            .options(
                joinedload(PickupRequest.payment_details),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
            )
            .with_for_update(of=PickupRequest)
            .execution_options(populate_existing=True)
        )
        res = await self.session.exec(query)
        return list(res.unique().all())

    @staticmethod
    def _cod_payout_expression() -> ColumnElement[float]:
        """
        Per-row merchant COD payout in SQL; mirrors `services.cod_payout.cod_payout_amount`
        (decision D26, plan B7). New TO_PAY rows keep the freight in `freight_collectible`,
        so `cod_amount` is the goods only and is paid out as is. Legacy TO_PAY +
        `add_shipping_to_cod` rows (no `billing_channel` marker) still hold the freight
        inside `cod_amount`, so it is withheld for the carrier; never negative.
        """
        is_legacy_row = ~sa.cast(col(PaymentDetails.pricing_breakdown), JSONB).has_key(
            BILLING_CHANNEL_BREAKDOWN_KEY
        )
        carrier_freight = case(
            (
                and_(
                    col(PaymentDetails.freight_payment_mode) == FreightPaymentMode.TO_PAY,
                    col(PaymentDetails.add_shipping_to_cod) == True,  # noqa: E712
                    is_legacy_row,
                ),
                func.coalesce(col(PaymentDetails.total_logistics_cost), 0.0),
            ),
            else_=0.0,
        )
        return func.greatest(
            func.coalesce(col(PaymentDetails.cod_amount), 0.0) - carrier_freight, 0.0
        )

    @staticmethod
    def _went_through_rto_clause() -> ColumnElement[bool]:
        """Correlated EXISTS: the activity ledger shows a transition into RTO_INITIATED."""
        return (
            select(ShipmentActivity.id)
            .where(
                ShipmentActivity.pickup_id == PickupRequest.id,
                ShipmentActivity.diff["status"]["new"].as_string()  # type: ignore[index]
                == PickupStatus.RTO_INITIATED.value,
            )
            .exists()
        )

    async def load_integrity_audit_snapshot(
        self,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> Tuple[
        List[UserWallet],
        List[WalletTransaction],
        List[PickupRequest],
        List[BillingInvoice],
        List[CodRemittance],
        List[Manifest],
    ]:
        """
        Loads tenant-scoped (or user-scoped) wallets, completed transactions,
        shipments with payment details, GST billing invoices, COD remittances,
        and manifests for cross-ledger integrity verification.
        """
        wallet_filters = [UserWallet.tenant_id == tenant_id]
        txn_filters = [
            WalletTransaction.tenant_id == tenant_id,
            WalletTransaction.status == WalletTxnStatus.COMPLETED,
        ]
        shipment_filters = [PickupRequest.tenant_id == tenant_id]
        invoice_filters = [BillingInvoice.tenant_id == tenant_id]
        remittance_filters = [CodRemittance.tenant_id == tenant_id]

        if user_id is not None:
            wallet_filters.append(UserWallet.user_id == user_id)
            txn_filters.append(WalletTransaction.user_id == user_id)
            shipment_filters.append(PickupRequest.created_by_user_id == user_id)
            invoice_filters.append(BillingInvoice.merchant_user_id == user_id)
            remittance_filters.append(CodRemittance.merchant_user_id == user_id)

        wallets = list(
            (await self.session.exec(select(UserWallet).where(*wallet_filters))).all()
        )
        transactions = list(
            (
                await self.session.exec(
                    select(WalletTransaction)
                    .where(*txn_filters)
                    .order_by(WalletTransaction.created_at.asc())
                )
            ).all()
        )
        shipments = list(
            (
                await self.session.exec(
                    select(PickupRequest)
                    .where(*shipment_filters)
                    .options(joinedload(PickupRequest.payment_details))  # type: ignore
                )
            )
            .unique()
            .all()
        )
        invoices = list(
            (
                await self.session.exec(select(BillingInvoice).where(*invoice_filters))
            ).all()
        )
        remittances = list(
            (
                await self.session.exec(
                    select(CodRemittance).where(*remittance_filters)
                )
            ).all()
        )
        manifests = list(
            (
                await self.session.exec(
                    select(Manifest).where(Manifest.tenant_id == tenant_id)
                )
            ).all()
        )
        return wallets, transactions, shipments, invoices, remittances, manifests

    async def list_active_measurement_pickup_ids(self, tenant_id: uuid.UUID) -> Set[uuid.UUID]:
        """
        Shipments of the tenant that have an active measurement (the billing basis).

        Used by the integrity audit to warn about blind LRs still billed at the floor
        ("measurement pending", plan B5).

        Args:
            tenant_id: Owning tenant (strict isolation).

        Returns:
            The set of pickup ids with an active `shipment_measurements` row.
        """
        rows = await self.session.exec(
            select(ShipmentMeasurement.pickup_id).where(
                ShipmentMeasurement.tenant_id == tenant_id,
                ShipmentMeasurement.is_active == True,  # noqa: E712
            )
        )
        return set(rows.all())

