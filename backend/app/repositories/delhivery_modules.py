import hashlib
import uuid
from datetime import date
from typing import Dict, List, Optional, Sequence

from sqlalchemy import Integer, and_, cast, desc, or_, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.delhivery_modules import (
    BillingInvoice,
    CodRemittance,
    InvoiceNoteType,
    SupportTicket,
    SupportTicketMessage,
    TicketStatus,
    WeightDispute,
)
from app.models.pickups import (
    Address,
    CodRemittanceStatus,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
)
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import WalletTransaction, WalletTxnType
from app.repositories.wallet import WalletRepository

CUSTOMER_SENDER_ROLE = UserRole.customer.value
"""`SupportTicketMessage.sender_role` value written for shipper (customer) messages."""

ADVISORY_LOCK_KEY_BYTES = 8
"""A Postgres advisory lock key is a signed 64-bit integer (8 bytes)."""
DOCUMENT_SERIAL_REGEX = "^[0-9]{6}$"
"""Only the new 6-digit serial format counts; legacy numbers never match."""
TICKET_NUMBER_REGEX = "^TKT-[0-9]{8}-[0-9]+$"
"""Support ticket numbers `TKT-<yyyymmdd>-<serial>`; only these count for the next serial."""
TICKET_SERIAL_PART = 3
"""1-based `-`-separated part of a ticket number holding the serial."""
TICKET_LOCK_NAMESPACE = "support-ticket-series"
DOCUMENT_SERIES_LOCK_TIMEOUT = "20s"
"""Longest wait for a GST series lock (BUG-03); well under the 120 s frontend proxy timeout."""
LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


class DocumentSeriesBusyError(Exception):
    """The GST series lock was not granted in time; the caller's transaction is aborted (retryable)."""


def ticket_series_lock_key(tenant_id: uuid.UUID) -> int:
    """Stable signed 64-bit advisory-lock key of a tenant's support-ticket number series."""
    raw = f"{TICKET_LOCK_NAMESPACE}:{tenant_id}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()[:ADVISORY_LOCK_KEY_BYTES]
    return int.from_bytes(digest, "big", signed=True)


def document_series_lock_key(
    tenant_id: uuid.UUID, financial_year: str, note_type: str
) -> int:
    """
    Stable signed 64-bit advisory-lock key for one GST document series
    (tenant + financial year + INVOICE / CREDIT_NOTE / DEBIT_NOTE).

    Python's built-in `hash()` is salted per process, so a SHA-256 digest is
    used to make every API worker agree on the same key.
    """
    raw = f"{tenant_id}:{financial_year}:{note_type}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()[:ADVISORY_LOCK_KEY_BYTES]
    return int.from_bytes(digest, "big", signed=True)


class DelhiveryModulesRepository:
    """
    Data Access Object (DAO) for Delhivery One parity modules:
    - CodRemittance
    - BillingInvoice
    - SupportTicket & SupportTicketMessage
    - WeightDispute

    Every query enforces strict multi-tenant isolation via `tenant_id`.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # 0. Shared lookups
    # ------------------------------------------------------------------

    async def get_tenant_user(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[User]:
        """Returns the user only if it belongs to the tenant."""
        stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        return (await self.session.exec(stmt)).first()

    async def get_user_emails(
        self, tenant_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
    ) -> Dict[uuid.UUID, str]:
        """
        Maps user id -> email for the given users of this tenant in one query
        (staff views label each tenant-wide finance row with its merchant).
        """
        unique_ids = list(dict.fromkeys(user_ids))
        if not unique_ids:
            return {}
        stmt = select(User.id, User.email).where(
            User.tenant_id == tenant_id, col(User.id).in_(unique_ids)
        )
        rows = (await self.session.exec(stmt)).all()
        return {user_id: email for user_id, email in rows}

    async def get_address(self, address_id: Optional[uuid.UUID]) -> Optional[Address]:
        """Loads an address snapshot by id (None-safe)."""
        if address_id is None:
            return None
        return await self.session.get(Address, address_id)

    async def get_tenant(self, tenant_id: uuid.UUID) -> Optional[Tenant]:
        """Loads the tenant (settings carry the supplier GST profile and rate card)."""
        return await self.session.get(Tenant, tenant_id)

    # ------------------------------------------------------------------
    # 1. COD Remittances
    # ------------------------------------------------------------------

    async def list_remittances(
        self,
        tenant_id: uuid.UUID,
        merchant_user_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
        processed_date: Optional[date] = None,
    ) -> List[CodRemittance]:
        """
        Lists remittance batches. `merchant_user_id=None` means tenant-wide (staff);
        otherwise strictly that merchant's rows (an empty list if they have none).
        """
        stmt = select(CodRemittance).where(CodRemittance.tenant_id == tenant_id)
        if merchant_user_id is not None:
            stmt = stmt.where(CodRemittance.merchant_user_id == merchant_user_id)

        if search and search.strip():
            q = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    col(CodRemittance.remittance_number).ilike(q),
                    col(CodRemittance.bank_utr).ilike(q),
                )
            )
        if processed_date is not None:
            stmt = stmt.where(CodRemittance.processed_date == processed_date)

        stmt = stmt.order_by(
            desc(col(CodRemittance.processed_date)),
            desc(col(CodRemittance.created_at)),
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def get_remittance_by_identifier(
        self, tenant_id: uuid.UUID, identifier: str
    ) -> Optional[CodRemittance]:
        cleaned = identifier.strip()
        try:
            remit_uuid = uuid.UUID(cleaned)
            stmt = select(CodRemittance).where(
                CodRemittance.id == remit_uuid,
                CodRemittance.tenant_id == tenant_id,
            )
            found = (await self.session.exec(stmt)).first()
            if found:
                return found
        except ValueError:
            pass

        stmt = select(CodRemittance).where(
            CodRemittance.remittance_number == cleaned,
            CodRemittance.tenant_id == tenant_id,
        )
        return (await self.session.exec(stmt)).first()

    @staticmethod
    def _cod_settled_to_wallet_clause() -> ColumnElement[bool]:
        """Correlated EXISTS: a COD_SETTLEMENT wallet credit already exists for the shipment."""
        return (
            select(WalletTransaction.id)
            .where(
                WalletTransaction.shipment_id == PickupRequest.id,
                WalletTransaction.tenant_id == PickupRequest.tenant_id,
                WalletTransaction.txn_type == WalletTxnType.COD_SETTLEMENT.value,
            )
            .exists()
        )

    async def lock_cod_shipments_for_remittance(
        self,
        tenant_id: uuid.UUID,
        merchant_user_id: Optional[uuid.UUID] = None,
        shipment_ids: Optional[Sequence[uuid.UUID]] = None,
    ) -> List[PickupRequest]:
        """
        Locks (`FOR UPDATE OF pickups`) the COD shipments a remittance batch may touch,
        filtered by explicit ids and/or merchant. No eligibility filter here: callers
        re-read eligibility with `get_remittable_cod_shipments` AFTER the lock so the
        second statement sees anything a concurrent COD settlement / batch committed.
        """
        stmt = (
            select(PickupRequest)
            .join(PaymentDetails, col(PaymentDetails.pickup_id) == col(PickupRequest.id))
            .where(
                PickupRequest.tenant_id == tenant_id,
                PaymentDetails.is_cod.is_(True),  # type: ignore[attr-defined]
            )
            .order_by(col(PickupRequest.id))
            .with_for_update(of=PickupRequest)
        )
        if shipment_ids:
            stmt = stmt.where(col(PickupRequest.id).in_(list(shipment_ids)))
        if merchant_user_id is not None:
            stmt = stmt.where(PickupRequest.created_by_user_id == merchant_user_id)
        result = await self.session.exec(stmt)
        return list(result.all())

    async def get_remittable_cod_shipments(
        self,
        tenant_id: uuid.UUID,
        merchant_user_id: uuid.UUID,
        shipment_ids: Optional[Sequence[uuid.UUID]] = None,
    ) -> List[PickupRequest]:
        """
        One merchant's COD shipments that can be paid out by bank remittance:
        delivered (COMPLETED), never through RTO (the cash was never collected),
        not yet REMITTED and not already credited to the wallet via COD settlement.
        """
        stmt = (
            select(PickupRequest)
            .join(PaymentDetails, col(PaymentDetails.pickup_id) == col(PickupRequest.id))
            .where(
                PickupRequest.tenant_id == tenant_id,
                PickupRequest.created_by_user_id == merchant_user_id,
                PickupRequest.status == PickupStatus.COMPLETED,
                PaymentDetails.is_cod.is_(True),  # type: ignore[attr-defined]
                PaymentDetails.cod_remittance_status != CodRemittanceStatus.REMITTED,
                ~WalletRepository._went_through_rto_clause(),
                ~self._cod_settled_to_wallet_clause(),
            )
            .options(selectinload(PickupRequest.payment_details))  # type: ignore[arg-type]
            .order_by(col(PickupRequest.id))
            .execution_options(populate_existing=True)
        )
        if shipment_ids:
            stmt = stmt.where(col(PickupRequest.id).in_(list(shipment_ids)))
        result = await self.session.exec(stmt)
        return list(result.all())

    async def save_remittance(
        self, remittance: CodRemittance, commit: bool = True
    ) -> CodRemittance:
        self.session.add(remittance)
        if commit:
            await self.session.commit()
            await self.session.refresh(remittance)
        else:
            await self.session.flush()
        return remittance

    # ------------------------------------------------------------------
    # 2. Billing Invoices
    # ------------------------------------------------------------------

    async def list_invoices(
        self,
        tenant_id: uuid.UUID,
        merchant_user_id: Optional[uuid.UUID] = None,
        note_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[BillingInvoice]:
        """
        Lists GST documents. `merchant_user_id=None` means tenant-wide (staff);
        otherwise strictly that merchant's rows (an empty list if they have none).
        """
        stmt = select(BillingInvoice).where(BillingInvoice.tenant_id == tenant_id)
        if merchant_user_id is not None:
            stmt = stmt.where(BillingInvoice.merchant_user_id == merchant_user_id)

        if note_type and note_type.strip():
            stmt = stmt.where(BillingInvoice.note_type == note_type.strip().upper())

        if search and search.strip():
            q = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    col(BillingInvoice.invoice_number).ilike(q),
                    col(BillingInvoice.service_type).ilike(q),
                )
            )

        stmt = stmt.order_by(
            desc(col(BillingInvoice.invoice_date)),
            desc(col(BillingInvoice.created_at)),
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def get_invoice_by_identifier(
        self, tenant_id: uuid.UUID, identifier: str
    ) -> Optional[BillingInvoice]:
        cleaned = identifier.strip()
        try:
            inv_uuid = uuid.UUID(cleaned)
            stmt = select(BillingInvoice).where(
                BillingInvoice.id == inv_uuid,
                BillingInvoice.tenant_id == tenant_id,
            )
            found = (await self.session.exec(stmt)).first()
            if found:
                return found
        except ValueError:
            pass

        stmt = select(BillingInvoice).where(
            BillingInvoice.invoice_number == cleaned,
            BillingInvoice.tenant_id == tenant_id,
        )
        return (await self.session.exec(stmt)).first()

    async def save_invoice(
        self, invoice: BillingInvoice, commit: bool = True
    ) -> BillingInvoice:
        self.session.add(invoice)
        if commit:
            await self.session.commit()
            await self.session.refresh(invoice)
        else:
            await self.session.flush()
        return invoice

    async def get_shipment_billing_document(
        self,
        tenant_id: uuid.UUID,
        shipment_id: uuid.UUID,
        note_type: str = InvoiceNoteType.INVOICE.value,
    ) -> Optional[BillingInvoice]:
        """
        The register row (earliest) of the given note type whose line items reference
        the shipment, via JSONB containment (`line_items @> [{"shipment_id": ...}]`).
        """
        stmt = (
            select(BillingInvoice)
            .where(
                BillingInvoice.tenant_id == tenant_id,
                BillingInvoice.note_type == note_type,
                col(BillingInvoice.line_items).contains(
                    [{"shipment_id": str(shipment_id)}]
                ),
            )
            .order_by(col(BillingInvoice.created_at), col(BillingInvoice.invoice_number))
            .limit(1)
        )
        return (await self.session.exec(stmt)).first()

    async def lock_document_series(
        self, tenant_id: uuid.UUID, financial_year: str, note_type: str
    ) -> None:
        """
        `pg_advisory_xact_lock(key)` for one GST series: serializes every allocator
        of that series until the CALLER'S transaction commits or rolls back.
        Re-entrant within the same transaction.

        Waits at most `DOCUMENT_SERIES_LOCK_TIMEOUT` (BUG-03): a transaction that holds the
        series for long must not hang every other booking past the proxy timeout. The previous
        `lock_timeout` is restored in the same round trip as the lock.

        Raises:
            DocumentSeriesBusyError: not granted in time. Nothing of the caller's transaction
                is committed, so the request can simply be retried.
        """
        lock_key = document_series_lock_key(tenant_id, financial_year, note_type)
        previous = (
            await self.session.exec(
                text(
                    "SELECT current_setting('lock_timeout') AS previous, "
                    "set_config('lock_timeout', :timeout, true)"
                ).bindparams(timeout=DOCUMENT_SERIES_LOCK_TIMEOUT)
            )
        ).first()[0]
        try:
            await self.session.exec(
                text(
                    "SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT)), "
                    "set_config('lock_timeout', :previous, true)"
                ).bindparams(lock_key=lock_key, previous=previous)
            )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE_SQLSTATE:
                raise DocumentSeriesBusyError(note_type) from exc
            raise

    async def next_document_serial(
        self, tenant_id: uuid.UUID, number_prefix: str
    ) -> int:
        """`max(serial) + 1` over the tenant's existing numbers that start with `number_prefix`."""
        serial_text = func.substr(
            col(BillingInvoice.invoice_number), len(number_prefix) + 1
        )
        stmt = select(func.max(cast(serial_text, Integer))).where(
            BillingInvoice.tenant_id == tenant_id,
            func.left(col(BillingInvoice.invoice_number), len(number_prefix))
            == number_prefix,
            serial_text.op("~")(DOCUMENT_SERIAL_REGEX),
        )
        current_max = (await self.session.exec(stmt)).one()
        return int(current_max or 0) + 1

    async def allocate_document_sequence(
        self,
        tenant_id: uuid.UUID,
        financial_year: str,
        note_type: str,
        number_prefix: str,
    ) -> int:
        """
        Allocates the next gap-free serial for one GST series inside the CALLER'S
        transaction (no commit here): advisory lock, then `max + 1`.
        A rollback releases the lock without leaving a row, so the next caller
        reuses that serial: no gaps and no duplicates.
        """
        await self.lock_document_series(tenant_id, financial_year, note_type)
        return await self.next_document_serial(tenant_id, number_prefix)

    async def get_open_tickets_by_tracking_id(
        self,
        tenant_id: uuid.UUID,
        tracking_id: str,
        sub_category: Optional[str] = None,
    ) -> List[SupportTicket]:
        """
        OPEN tickets of the tenant linked to an AWB, optionally only one sub-category
        (e.g. the weight-claim ticket a claim resolution may auto-resolve).
        """
        stmt = select(SupportTicket).where(
            SupportTicket.tenant_id == tenant_id,
            SupportTicket.tracking_id == tracking_id.strip(),
            SupportTicket.status == TicketStatus.OPEN.value,
        )
        if sub_category is not None:
            stmt = stmt.where(SupportTicket.sub_category == sub_category)
        result = await self.session.exec(stmt)
        return list(result.all())

    async def get_shipment_statuses(
        self, tenant_id: uuid.UUID, shipment_ids: Sequence[uuid.UUID]
    ) -> Dict[uuid.UUID, PickupStatus]:
        """Current status of each listed shipment of the tenant (one query)."""
        if not shipment_ids:
            return {}
        stmt = select(PickupRequest.id, PickupRequest.status).where(
            PickupRequest.tenant_id == tenant_id,
            col(PickupRequest.id).in_(list(set(shipment_ids))),
        )
        rows = (await self.session.exec(stmt)).all()
        return {shipment_id: shipment_status for shipment_id, shipment_status in rows}

    # ------------------------------------------------------------------
    # 3. Support Tickets
    # ------------------------------------------------------------------

    async def allocate_ticket_serial(self, tenant_id: uuid.UUID) -> int:
        """
        Next support-ticket serial of the tenant (the `NNNN` of `TKT-<date>-NNNN`), allocated
        inside the CALLER'S transaction under a per-tenant `pg_advisory_xact_lock`, so two
        tickets raised at the same moment never get the same number. `max + 1` over the
        well-formed numbers (not a row count) also survives deleted tickets.
        """
        await self.session.exec(
            text("SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))").bindparams(
                lock_key=ticket_series_lock_key(tenant_id)
            )
        )
        serial_text = func.split_part(col(SupportTicket.ticket_number), "-", TICKET_SERIAL_PART)
        stmt = select(func.max(cast(serial_text, Integer))).where(
            SupportTicket.tenant_id == tenant_id,
            col(SupportTicket.ticket_number).op("~")(TICKET_NUMBER_REGEX),
        )
        current = (await self.session.exec(stmt)).one()
        return int(current or 0) + 1

    async def support_ticket_summary(
        self, tenant_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> dict:
        """
        Ticket counters in one round trip. "Who replied last" comes from a
        correlated sub-select on the newest thread message of each ticket.

        Args:
            tenant_id: Tenant scope.
            user_id: Restrict to one shipper's tickets (customers), or None for the tenant.
        """
        last_sender_role = (
            select(SupportTicketMessage.sender_role)
            .where(SupportTicketMessage.ticket_id == SupportTicket.id)
            .order_by(desc(col(SupportTicketMessage.created_at)))
            .limit(1)
            .correlate(SupportTicket)
            .scalar_subquery()
        )
        is_open = col(SupportTicket.status) == TicketStatus.OPEN.value
        shipper_replied_last = or_(
            last_sender_role == CUSTOMER_SENDER_ROLE, last_sender_role.is_(None)
        )
        stmt = select(
            func.count().filter(is_open),
            func.count().filter(col(SupportTicket.status) == TicketStatus.RESOLVED.value),
            func.count().filter(col(SupportTicket.status) == TicketStatus.CLOSED.value),
            func.count().filter(and_(is_open, ~shipper_replied_last)),
            func.count().filter(and_(is_open, shipper_replied_last)),
        ).where(SupportTicket.tenant_id == tenant_id)
        if user_id is not None:
            stmt = stmt.where(SupportTicket.user_id == user_id)
        open_n, resolved_n, closed_n, need_input_n, awaiting_n = (
            await self.session.exec(stmt)
        ).one()
        return {
            "open": int(open_n or 0),
            "resolved": int(resolved_n or 0),
            "closed": int(closed_n or 0),
            "need_your_input": int(need_input_n or 0),
            "awaiting_support": int(awaiting_n or 0),
        }

    async def list_tickets(
        self,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[SupportTicket]:
        stmt = select(SupportTicket).where(SupportTicket.tenant_id == tenant_id)
        if user_id is not None:
            stmt = stmt.where(SupportTicket.user_id == user_id)

        if status and status.strip():
            stmt = stmt.where(SupportTicket.status == status.strip().upper())

        if search and search.strip():
            q = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    col(SupportTicket.ticket_number).ilike(q),
                    col(SupportTicket.subject).ilike(q),
                    col(SupportTicket.sub_category).ilike(q),
                    col(SupportTicket.tracking_id).ilike(q),
                )
            )

        stmt = stmt.order_by(
            desc(col(SupportTicket.updated_at)),
            desc(col(SupportTicket.created_at)),
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def get_ticket_by_identifier(
        self, tenant_id: uuid.UUID, identifier: str
    ) -> Optional[SupportTicket]:
        cleaned = identifier.strip()
        try:
            tkt_uuid = uuid.UUID(cleaned)
            stmt = select(SupportTicket).where(
                SupportTicket.id == tkt_uuid,
                SupportTicket.tenant_id == tenant_id,
            )
            found = (await self.session.exec(stmt)).first()
            if found:
                return found
        except ValueError:
            pass

        stmt = select(SupportTicket).where(
            SupportTicket.ticket_number == cleaned,
            SupportTicket.tenant_id == tenant_id,
        )
        return (await self.session.exec(stmt)).first()

    async def list_ticket_messages(
        self, ticket_id: uuid.UUID
    ) -> List[SupportTicketMessage]:
        stmt = (
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == ticket_id)
            .order_by(col(SupportTicketMessage.created_at).asc())
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def save_ticket(
        self, ticket: SupportTicket, commit: bool = True
    ) -> SupportTicket:
        self.session.add(ticket)
        if commit:
            await self.session.commit()
            await self.session.refresh(ticket)
        else:
            await self.session.flush()
        return ticket

    async def save_ticket_message(
        self, message: SupportTicketMessage, commit: bool = True
    ) -> SupportTicketMessage:
        self.session.add(message)
        if commit:
            await self.session.commit()
            await self.session.refresh(message)
        else:
            await self.session.flush()
        return message

    # ------------------------------------------------------------------
    # 4. Weight Disputes & Shipment Lookup
    # ------------------------------------------------------------------

    async def find_shipment_by_tracking_id(
        self, tenant_id: uuid.UUID, tracking_id: str
    ) -> Optional[PickupRequest]:
        stmt = (
            select(PickupRequest)
            .where(
                PickupRequest.tenant_id == tenant_id,
                PickupRequest.tracking_id == tracking_id.strip(),
            )
            .options(
                selectinload(PickupRequest.payment_details),
                selectinload(PickupRequest.packages),
            )
        )
        return (await self.session.exec(stmt)).first()

    async def list_weight_disputes(
        self,
        tenant_id: uuid.UUID,
        merchant_user_id: Optional[uuid.UUID] = None,
        search: Optional[str] = None,
        claim_status: Optional[str] = None,
    ) -> List[WeightDispute]:
        """
        Lists weight disputes. `merchant_user_id=None` means tenant-wide (staff);
        otherwise strictly that merchant's rows (an empty list if they have none).
        """
        stmt = select(WeightDispute).where(WeightDispute.tenant_id == tenant_id)
        if merchant_user_id is not None:
            stmt = stmt.where(WeightDispute.merchant_user_id == merchant_user_id)

        if claim_status and claim_status.strip():
            stmt = stmt.where(WeightDispute.claim_status == claim_status.strip().upper())

        if search and search.strip():
            q = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    col(WeightDispute.tracking_id).ilike(q),
                    col(WeightDispute.order_reference_id).ilike(q),
                )
            )

        stmt = stmt.order_by(
            desc(col(WeightDispute.updated_at)),
            desc(col(WeightDispute.raised_at)),
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def get_weight_dispute_by_id(
        self, tenant_id: uuid.UUID, dispute_id: uuid.UUID, for_update: bool = False
    ) -> Optional[WeightDispute]:
        """Fetches a dispute; `for_update=True` row-locks it until the transaction ends."""
        stmt = select(WeightDispute).where(
            WeightDispute.id == dispute_id,
            WeightDispute.tenant_id == tenant_id,
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.exec(stmt)).first()

    async def get_weight_dispute_by_tracking_id(
        self, tenant_id: uuid.UUID, tracking_id: str, for_update: bool = False
    ) -> Optional[WeightDispute]:
        """Fetches a dispute by AWB; `for_update=True` row-locks it until the transaction ends."""
        stmt = select(WeightDispute).where(
            WeightDispute.tenant_id == tenant_id,
            WeightDispute.tracking_id == tracking_id.strip(),
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.exec(stmt)).first()

    async def save_weight_dispute(
        self, dispute: WeightDispute, commit: bool = True
    ) -> WeightDispute:
        self.session.add(dispute)
        if commit:
            await self.session.commit()
            await self.session.refresh(dispute)
        else:
            await self.session.flush()
        return dispute
