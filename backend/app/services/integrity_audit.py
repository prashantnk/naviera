"""
Live wallet, GST and operations integrity audit (`GET /api/v1/wallet/audit-integrity`).

Moved out of `services/wallet.py` (plan B11) so wallet mutations and the audit that
checks them no longer share a file. It cross-checks invariants every money path must
keep. Amounts are compared exactly after rounding to the paisa (plan §2.0 "Money"):

1. WALLET_BALANCE   wallet balance == sum of its completed ledger rows, and every row's
                    closing == opening + signed amount.
2. PREPAID_LEDGER   a live wallet-billed shipment has its booking SPEND and its GST INVOICE.
3. COD_REMITTANCE   a REMITTED COD shipment has a COD_SETTLEMENT row or a remittance batch.
4. MANIFEST_STATE   an ASSIGNED shipment sits on an active pickup request.
For every **wallet-billed** shipment (PREPAID + customer POSTPAID; staff-booked POSTPAID
and TO_PAY excluded, plan X7):
5. BILL_LEDGER      net debited (Σ bill debits − Σ refunds) == the bill (0 once cancelled).
6. GST_NOTES        INVOICE + DEBIT_NOTEs − CREDIT_NOTEs == the bill (0 once cancelled);
                    separate charges (Mathadi/union) carry their own notes and are excluded.
7. COLLECTIBLE      until Delivered, a COD-with-shipping row holds goods + freight in
                    `cod_amount` (goods never above the declared value), and no
                    TO_PAY-style freight is left in `freight_collectible`.
8. NOTE_COVERAGE    every wallet ledger row of the shipment has its own GST document.
Warnings (never fail the audit): MEASUREMENT_PENDING, a blind LR picked up without
"Actual pieces" and still billed at the floor (plan B5).

Spring Boot analogy: a read-only `@Service` running a nightly reconciliation report.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Set

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.money import ZERO_MONEY, to_money
from app.core.permissions import can_view_tenant_finance
from app.models.delhivery_modules import BillingInvoice, CodRemittance, InvoiceNoteType
from app.models.manifests import ManifestStatus
from app.models.pickups import CodRemittanceStatus, FreightPaymentMode, PickupRequest, PickupStatus
from app.models.tenants import Tenant, User
from app.models.wallet import WALLET_COD_UTR_PREFIX, WalletTransaction, WalletTxnType, _utc_now_naive
from app.repositories.wallet import WalletRepository
from app.schemas.v1.wallet import WalletAuditDiscrepancy, WalletIntegrityAuditResponse
from app.services.cod_payout import cod_payout_amount, is_collectible_frozen
from app.services.repricing import (
    BILL_CREDIT_TYPES,
    BILL_DEBIT_TYPES,
    SEPARATE_CHARGE_TYPES,
    is_wallet_billed,
    net_debited,
)

CREDIT_TXN_TYPES = frozenset(
    {
        WalletTxnType.RECHARGE,
        WalletTxnType.REFUND,
        WalletTxnType.COD_SETTLEMENT,
        WalletTxnType.CHARGE_REVERSAL,
    }
)
"""Ledger rows that add to a wallet balance; every other completed row subtracts."""

FULL_REFUND_STATUSES = frozenset(
    {
        PickupStatus.CANCELLED,
        PickupStatus.QC_FAILED,
        PickupStatus.REJECTED_AT_PICKUP,
    }
)
"""Terminal pre-pickup statuses refunded to ₹0 while the historical bill stays recorded."""

NOTE_COVERED_TXN_TYPES = BILL_DEBIT_TYPES | BILL_CREDIT_TYPES | SEPARATE_CHARGE_TYPES
"""Shipment ledger rows that must each have a GST document (INVOICE / DEBIT_NOTE / CREDIT_NOTE)."""

ACTIVE_MANIFEST_STATUSES = frozenset({ManifestStatus.SCHEDULED, ManifestStatus.OUT_FOR_PICKUP})
PICKED_UP_STATUSES = frozenset(
    {
        PickupStatus.IN_TRANSIT,
        PickupStatus.EXCEPTION,
        PickupStatus.RTO_INITIATED,
        PickupStatus.COMPLETED,
    }
)
"""Statuses after which a blind LR has physically left the merchant (measurement expected)."""

SEPARATE_CHARGE_LINE_FLAG = "separate_charge"
"""GST line-item flag set on notes for charges outside the bill (see DelhiveryModulesService)."""


def _enum_value(value: object) -> str:
    """Raw string of an enum member or plain string column."""
    return value.value if hasattr(value, "value") else str(value)


def _signed_txn_amount(txn: WalletTransaction) -> Decimal:
    """Signed ledger impact (+credit, −debit) of a completed transaction."""
    amount = to_money(txn.amount)
    return amount if _enum_value(txn.txn_type) in {t.value for t in CREDIT_TXN_TYPES} else -amount


def _invoice_shipment_id(invoice: BillingInvoice) -> Optional[str]:
    """Shipment a GST document belongs to: the M-B4 column, else the legacy line-item link."""
    if invoice.shipment_id is not None:
        return str(invoice.shipment_id)
    for item in invoice.line_items or []:
        if isinstance(item, dict) and item.get("shipment_id"):
            return str(item["shipment_id"])
    return None


def _is_separate_charge_note(invoice: BillingInvoice) -> bool:
    """True for a note issued for a charge outside the bill (Mathadi / union)."""
    return any(
        isinstance(item, dict) and item.get(SEPARATE_CHARGE_LINE_FLAG)
        for item in invoice.line_items or []
    )


@dataclass
class _ShipmentLedger:
    """Per-shipment wallet rows and GST documents gathered from the snapshot."""

    txns: List[WalletTransaction] = field(default_factory=list)
    invoices: List[BillingInvoice] = field(default_factory=list)

    def bill_by_notes(self) -> Decimal:
        """INVOICE + DEBIT_NOTEs − CREDIT_NOTEs, separate-charge notes excluded."""
        total = ZERO_MONEY
        for doc in self.invoices:
            if _is_separate_charge_note(doc):
                continue
            note = _enum_value(doc.note_type)
            amount = to_money(doc.total_amount)
            if note == InvoiceNoteType.CREDIT_NOTE.value:
                total -= amount
            elif note in (InvoiceNoteType.INVOICE.value, InvoiceNoteType.DEBIT_NOTE.value):
                total += amount
        return to_money(total)

    def has_note_type(self, note_type: InvoiceNoteType) -> bool:
        """Whether a document of this type exists for the shipment."""
        return any(_enum_value(doc.note_type) == note_type.value for doc in self.invoices)

    def covered_txn_count(self) -> int:
        """Number of ledger rows that each need their own GST document."""
        covered = {t.value for t in NOTE_COVERED_TXN_TYPES}
        return sum(1 for txn in self.txns if _enum_value(txn.txn_type) in covered)


class IntegrityAuditService:
    """Read-only reconciliation of wallets, the bill, GST documents and collectibles."""

    def __init__(self, wallet_repo: WalletRepository):
        self.wallet_repo = wallet_repo

    @staticmethod
    def _discrepancy(category: str, entity_id: object, reference: str, detail: str) -> WalletAuditDiscrepancy:
        """Builds one finding row."""
        return WalletAuditDiscrepancy(
            category=category, entity_id=str(entity_id), reference=reference, detail=detail
        )

    async def audit_tenant_integrity(self, user: User, tenant: Tenant) -> WalletIntegrityAuditResponse:
        """
        Runs every check over the tenant (finance staff) or over the caller's own data.

        Args:
            user: The caller; non-finance users are scoped to their own wallet and shipments.
            tenant: Tenant being audited (strict isolation).

        Returns:
            Counts, failing discrepancies and non-failing warnings.
        """
        scope_user_id = None if can_view_tenant_finance(user) else user.id
        (
            wallets,
            transactions,
            shipments,
            invoices,
            remittances,
            manifests,
        ) = await self.wallet_repo.load_integrity_audit_snapshot(
            tenant_id=tenant.id, user_id=scope_user_id
        )
        measured_ids = await self.wallet_repo.list_active_measurement_pickup_ids(tenant.id)
        ledgers = self._group_by_shipment(transactions, invoices)
        remitted_ids = {
            str(item["shipment_id"])
            for rem in remittances
            for item in rem.shipment_breakdown or []
            if isinstance(item, dict) and item.get("shipment_id")
        }
        bank_payouts = self._bank_payout_counts(remittances)
        active_manifest_ids = {m.id for m in manifests if m.status in ACTIVE_MANIFEST_STATUSES}

        discrepancies = self._check_wallet_balances(wallets, transactions)
        warnings: List[WalletAuditDiscrepancy] = []
        for shipment in shipments:
            ledger = ledgers.get(str(shipment.id), _ShipmentLedger())
            discrepancies.extend(self._check_shipment(shipment, ledger, remitted_ids, active_manifest_ids))
            discrepancies.extend(self._check_single_payout(shipment, ledger, bank_payouts))
            warning = self._measurement_pending_warning(shipment, measured_ids)
            if warning is not None:
                warnings.append(warning)

        return WalletIntegrityAuditResponse(
            passed=not discrepancies,
            checked_at=_utc_now_naive(),
            wallets_checked=len(wallets),
            transactions_checked=len(transactions),
            shipments_checked=len(shipments),
            invoices_checked=len(invoices),
            remittances_checked=len(remittances),
            discrepancy_count=len(discrepancies),
            discrepancies=discrepancies,
            warnings=warnings,
        )

    @staticmethod
    def _group_by_shipment(
        transactions: Iterable[WalletTransaction], invoices: Iterable[BillingInvoice]
    ) -> Dict[str, _ShipmentLedger]:
        """Indexes ledger rows and GST documents by shipment id."""
        ledgers: Dict[str, _ShipmentLedger] = {}
        for txn in transactions:
            if txn.shipment_id is not None:
                ledgers.setdefault(str(txn.shipment_id), _ShipmentLedger()).txns.append(txn)
        for doc in invoices:
            shipment_id = _invoice_shipment_id(doc)
            if shipment_id is not None:
                ledgers.setdefault(shipment_id, _ShipmentLedger()).invoices.append(doc)
        return ledgers

    def _check_wallet_balances(
        self, wallets: Iterable, transactions: Iterable[WalletTransaction]
    ) -> List[WalletAuditDiscrepancy]:
        """Check 1: per-row closing math and wallet balance vs ledger sum."""
        findings: List[WalletAuditDiscrepancy] = []
        by_wallet: Dict[uuid.UUID, List[WalletTransaction]] = {}
        for txn in transactions:
            by_wallet.setdefault(txn.wallet_id, []).append(txn)
            expected_closing = to_money(to_money(txn.opening_balance) + _signed_txn_amount(txn))
            if to_money(txn.closing_balance) != expected_closing:
                findings.append(
                    self._discrepancy(
                        "WALLET_BALANCE",
                        txn.id,
                        txn.receipt_number or "",
                        f"Transaction {txn.receipt_number} closing_balance (₹{to_money(txn.closing_balance)}) "
                        f"does not match opening_balance + signed_amount (₹{expected_closing}).",
                    )
                )
        for wallet in wallets:
            expected = to_money(sum((_signed_txn_amount(t) for t in by_wallet.get(wallet.id, [])), ZERO_MONEY))
            actual = to_money(wallet.balance)
            if actual != expected:
                findings.append(
                    self._discrepancy(
                        "WALLET_BALANCE",
                        wallet.id,
                        f"WALLET-{str(wallet.user_id)[:8].upper()}",
                        f"Wallet balance (₹{actual}) diverges from completed ledger sum (₹{expected}).",
                    )
                )
        return findings

    def _check_shipment(
        self,
        shipment: PickupRequest,
        ledger: _ShipmentLedger,
        remitted_ids: Set[str],
        active_manifest_ids: Set[uuid.UUID],
    ) -> List[WalletAuditDiscrepancy]:
        """Checks 2 to 8 for one shipment."""
        ref = shipment.tracking_id or shipment.order_reference_id or str(shipment.id)[:8].upper()
        findings: List[WalletAuditDiscrepancy] = []
        findings.extend(self._check_cod_remittance(shipment, ledger, remitted_ids, ref))
        if shipment.status == PickupStatus.ASSIGNED and (
            shipment.manifest_id is None or shipment.manifest_id not in active_manifest_ids
        ):
            findings.append(
                self._discrepancy(
                    "MANIFEST_STATE",
                    shipment.id,
                    ref,
                    f"Shipment {ref} is in ASSIGNED status but is not linked to an active "
                    "SCHEDULED or OUT_FOR_PICKUP pickup request.",
                )
            )
        payment = shipment.payment_details
        if payment is None or not is_wallet_billed(shipment):
            return findings
        findings.extend(self._check_wallet_billed(shipment, ledger, ref))
        return findings

    def _check_cod_remittance(
        self, shipment: PickupRequest, ledger: _ShipmentLedger, remitted_ids: Set[str], ref: str
    ) -> List[WalletAuditDiscrepancy]:
        """Check 3: a REMITTED COD shipment was paid out through the wallet or a batch."""
        payment = shipment.payment_details
        if not (
            payment is not None
            and payment.is_cod
            and payment.cod_remittance_status == CodRemittanceStatus.REMITTED
            and cod_payout_amount(payment) > 0.0
        ):
            return []
        settled = any(
            _enum_value(t.txn_type) == WalletTxnType.COD_SETTLEMENT.value for t in ledger.txns
        )
        if settled or str(shipment.id) in remitted_ids:
            return []
        return [
            self._discrepancy(
                "COD_REMITTANCE",
                shipment.id,
                ref,
                f"Remitted COD shipment {ref} has no matching COD_SETTLEMENT wallet transaction "
                "or CodRemittance batch record.",
            )
        ]

    @staticmethod
    def _bank_payout_counts(remittances: Iterable[CodRemittance]) -> Counter:
        """How many BANK remittance lines paid each shipment (wallet self-settle rows excluded)."""
        counts: Counter = Counter()
        for rem in remittances:
            if (rem.bank_utr or "").startswith(WALLET_COD_UTR_PREFIX):
                continue
            for item in rem.shipment_breakdown or []:
                if isinstance(item, dict) and item.get("shipment_id"):
                    counts[str(item["shipment_id"])] += 1
        return counts

    def _check_single_payout(
        self, shipment: PickupRequest, ledger: _ShipmentLedger, bank_payouts: Counter
    ) -> List[WalletAuditDiscrepancy]:
        """Check 3b (A-24): a COD shipment is paid out at most ONCE (bank batch or wallet)."""
        wallet_settlements = sum(
            1 for t in ledger.txns if _enum_value(t.txn_type) == WalletTxnType.COD_SETTLEMENT.value
        )
        payouts = wallet_settlements + bank_payouts.get(str(shipment.id), 0)
        if payouts <= 1:
            return []
        ref = shipment.tracking_id or str(shipment.id)
        return [
            self._discrepancy(
                "COD_DOUBLE_PAYOUT",
                shipment.id,
                ref,
                f"COD shipment {ref} was paid out {payouts} times (bank remittances + wallet "
                "settlements); it must be paid exactly once.",
            )
        ]

    def _check_wallet_billed(
        self, shipment: PickupRequest, ledger: _ShipmentLedger, ref: str
    ) -> List[WalletAuditDiscrepancy]:
        """Checks 2 and 5 to 8 for a wallet-billed shipment."""
        payment = shipment.payment_details
        findings: List[WalletAuditDiscrepancy] = []
        is_refunded = shipment.status in FULL_REFUND_STATUSES
        bill = to_money(payment.total_logistics_cost)
        expected = ZERO_MONEY if is_refunded else bill

        if not is_refunded and bill > ZERO_MONEY:
            if not any(_enum_value(t.txn_type) == WalletTxnType.SPEND.value for t in ledger.txns):
                findings.append(
                    self._discrepancy(
                        "PREPAID_LEDGER", shipment.id, ref,
                        f"Wallet-billed shipment {ref} is missing a COMPLETED SPEND wallet transaction.",
                    )
                )
            if not ledger.has_note_type(InvoiceNoteType.INVOICE):
                findings.append(
                    self._discrepancy(
                        "PREPAID_LEDGER", shipment.id, ref,
                        f"Wallet-billed shipment {ref} is missing a GST BillingInvoice (INVOICE).",
                    )
                )

        debited = to_money(net_debited(ledger.txns))
        if debited != expected:
            findings.append(
                self._discrepancy(
                    "BILL_LEDGER", shipment.id, ref,
                    f"Net debited for {ref} (₹{debited}) does not equal the bill (₹{expected}).",
                )
            )
        by_notes = ledger.bill_by_notes()
        if ledger.invoices and by_notes != expected:
            findings.append(
                self._discrepancy(
                    "GST_NOTES", shipment.id, ref,
                    f"INVOICE + DN − CN for {ref} (₹{by_notes}) does not equal the bill (₹{expected}).",
                )
            )
        if ledger.covered_txn_count() != len(ledger.invoices):
            findings.append(
                self._discrepancy(
                    "NOTE_COVERAGE", shipment.id, ref,
                    f"{ref} has {ledger.covered_txn_count()} wallet ledger rows but "
                    f"{len(ledger.invoices)} GST documents.",
                )
            )
        findings.extend(self._check_collectible(shipment, ref))
        return findings

    def _check_collectible(self, shipment: PickupRequest, ref: str) -> List[WalletAuditDiscrepancy]:
        """Check 7: the door collectible of a wallet-billed shipment, until Delivered."""
        payment = shipment.payment_details
        if is_collectible_frozen(shipment) or shipment.status in FULL_REFUND_STATUSES:
            return []
        problems: List[str] = []
        if to_money(payment.freight_collectible) != ZERO_MONEY and (
            payment.freight_payment_mode != FreightPaymentMode.TO_PAY
        ):
            problems.append(f"freight_collectible is ₹{to_money(payment.freight_collectible)} (expected ₹0.00)")
        if payment.is_cod:
            cod = to_money(payment.cod_amount)
            goods = cod - to_money(payment.total_logistics_cost) if payment.add_shipping_to_cod else cod
            if goods < ZERO_MONEY:
                problems.append(f"cod_amount ₹{cod} is below the freight it must include")
            elif goods > to_money(payment.shipment_total_value):
                problems.append(
                    f"goods COD ₹{goods} exceeds the declared value ₹{to_money(payment.shipment_total_value)}"
                )
        if not problems:
            return []
        return [self._discrepancy("COLLECTIBLE", shipment.id, ref, f"{ref}: " + "; ".join(problems) + ".")]

    def _measurement_pending_warning(
        self, shipment: PickupRequest, measured_ids: Set[uuid.UUID]
    ) -> Optional[WalletAuditDiscrepancy]:
        """Warning: a blind LR picked up without a measurement is still billed at the floor."""
        if not (
            shipment.is_blind_pickup
            and shipment.status in PICKED_UP_STATUSES
            and shipment.id not in measured_ids
        ):
            return None
        ref = shipment.tracking_id or str(shipment.id)[:8].upper()
        return self._discrepancy(
            "MEASUREMENT_PENDING",
            shipment.id,
            ref,
            f"Blind LR {ref} was picked up without Actual pieces; it stays billed at the floor "
            "until the hub records a measurement.",
        )


def get_integrity_audit_service(
    session: AsyncSession = Depends(get_session),
) -> IntegrityAuditService:
    """FastAPI factory (Spring: constructor injection of the repository)."""
    return IntegrityAuditService(WalletRepository(session))
