import base64
import csv
import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple
from urllib.parse import quote

from fastapi import Depends, HTTPException, status
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.permissions import (
    assert_can_manage_finance_or_wallet,
    can_view_tenant_finance,
)
from app.models.delhivery_modules import (
    CodRemittance,
    RemittanceState,
)
from app.models.pickups import (
    CodRemittanceStatus,
    FreightPaymentMode,
    PickupRequest,
)
from app.models.repricing import net_debited
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import (
    WALLET_COD_UTR_PREFIX,
    UserWallet,
    WalletServiceCategory,
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
    _utc_now_naive,
)
from app.repositories.shipments import is_b2b_shipment
from app.repositories.wallet import WalletRepository
from app.schemas.v1.wallet import (
    AdminOfflineCreditRequest,
    CodSettlementResponse,
    UpiConfirmRequest,
    UpiIntentRequest,
    UpiIntentResponse,
    UpiRechargeStatusResponse,
    VerifyUtrRequest,
    VerifyUtrResponse,
    WalletIntegrityAuditResponse,
    WalletOverviewResponse,
    WalletSummary,
    WalletTransactionRead,
)
from app.services.cod_payout import cod_payout_amount
from app.services.integrity_audit import IntegrityAuditService
from app.services.notifications import notify_wallet_recharge_status

IST = timezone(timedelta(hours=5, minutes=30))
"""Invoice dates, receipt numbers and the Indian financial year follow India Standard Time."""
FINANCIAL_YEAR_START_MONTH = 4
"""The Indian financial year runs 1 April to 31 March."""
RECEIPT_SHORT_ID_LENGTH = 8
"""Characters of the source UUID printed in a wallet receipt number."""
UTR_PATTERN = re.compile(r"^\d{12}$")
"""A bank / UPI transaction reference (UTR / RRN) is exactly 12 digits."""
UTR_REQUIRED_DETAIL = (
    "Enter the 12-digit UPI / bank reference (UTR) shown in your payment app. "
    "We need it to match your payment."
)
RECHARGE_REJECTED_REMARK_PREFIX = "Rejected by Admin"
CUSTOMER_COD_SETTLE_DETAIL = (
    "Delivered COD is paid to you by the Logismart finance team in the next COD "
    "remittance cycle; it cannot be moved to your wallet yourself."
)
"""403 for a customer calling settle-cod (Delhivery One `cod-remittance`: the carrier remits)."""
COD_MERCHANT_NOT_FOUND_DETAIL = "Merchant not found in this workspace."


def today_ist() -> date:
    """Today's calendar date in India (invoice dates, receipt numbers, financial year)."""
    return datetime.now(IST).date()


def indian_financial_year_label(on_date: date) -> str:
    """Four-digit Indian financial year code, e.g. 17 Oct 2026 -> "2627" (FY 2026-27)."""
    start_year = on_date.year if on_date.month >= FINANCIAL_YEAR_START_MONTH else on_date.year - 1
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def wallet_receipt_number(prefix: str, source_id: uuid.UUID) -> str:
    """
    Ledger receipt number `<PREFIX>-<FY>-<8 chars>` (e.g. `INV-2627-1A2B3C4D`).

    Args:
        prefix: Receipt family (REC, INV, CN, WAD, COD, FRC, ADC, RTO).
        source_id: UUID whose first characters make the receipt unique.

    Returns:
        The receipt number labelled with the current Indian financial year.
    """
    short_id = str(source_id)[:RECEIPT_SHORT_ID_LENGTH].upper()
    return f"{prefix}-{indian_financial_year_label(today_ist())}-{short_id}"


class WalletService:
    """
    Business service managing the User-Scoped Unified Wallet (`UserWallet`)
    and its immutable transaction ledger (`WalletTransaction`).
    """

    LEGACY_PLACEHOLDER_VPAS = {"logismart.logistics@icici", "logismart@icici"}
    UPI_NOT_CONFIGURED_DETAIL = (
        "UPI recharge is not configured for this workspace. Ask the workspace owner to "
        "add a merchant UPI ID in Settings."
    )
    DEFAULT_MIN_B2C_BALANCE = 0.0
    DEFAULT_MIN_B2B_BALANCE = 500.0
    LOGISMART_REAL_GSTIN = "06AAECL2138H1ZQ"
    LEGACY_FAKE_GSTINS = {"27AABCL1234F1Z5"}
    DEFAULT_GSTIN = "Not Configured"
    DEFAULT_AUTO_DETECT_DELAY_SECONDS = 5
    EXCEPTION_CHARGE_TXN_PREFIXES = {
        WalletTxnType.FREIGHT_COLLECTION: "FRC",
        WalletTxnType.ADDITIONAL_CHARGE: "ADC",
    }

    def __init__(self, wallet_repo: WalletRepository):
        self.wallet_repo = wallet_repo

    @classmethod
    def resolve_wallet_config(cls, tenant: Tenant) -> dict:
        """
        Effective wallet / UPI settings of a tenant, with defaults for unset keys.

        `merchant_vpa` has no default: it is `""` when the tenant has not set one (or
        still holds a legacy placeholder), and UPI recharge is then unavailable.
        """
        settings = tenant.settings or {}
        raw = settings.get("wallet_config") or {}
        company_cfg = settings.get("company") or {}
        raw_vpa = str(raw.get("merchant_vpa") or "").strip()
        resolved_vpa = "" if raw_vpa in cls.LEGACY_PLACEHOLDER_VPAS else raw_vpa
        candidate_gstin = str(
            raw.get("gstin")
            or company_cfg.get("gstin")
            or settings.get("gstin")
            or ""
        ).strip()
        if candidate_gstin in cls.LEGACY_FAKE_GSTINS:
            candidate_gstin = ""
        if not candidate_gstin and getattr(tenant, "slug", "") == "logismart":
            candidate_gstin = cls.LOGISMART_REAL_GSTIN
        return {
            "merchant_vpa": resolved_vpa,
            "merchant_name": str(
                raw.get("merchant_name")
                or company_cfg.get("legal_name")
                or tenant.name
            ),
            "min_wallet_balance_b2c": float(
                raw.get("min_wallet_balance_b2c", cls.DEFAULT_MIN_B2C_BALANCE)
            ),
            "min_wallet_balance_b2b": float(
                raw.get("min_wallet_balance_b2b", cls.DEFAULT_MIN_B2B_BALANCE)
            ),
            "strict_finlock": bool(raw.get("strict_finlock", False)),
            "auto_detect_upi": bool(raw.get("auto_detect_upi", False)),
            "auto_detect_delay_seconds": int(
                raw.get(
                    "auto_detect_delay_seconds",
                    cls.DEFAULT_AUTO_DETECT_DELAY_SECONDS,
                )
            ),
            "gstin": candidate_gstin or cls.DEFAULT_GSTIN,
        }

    @staticmethod
    def _generate_qr_svg_data_url(upi_uri: str) -> str:
        """
        Renders an NPCI UPI URI into a crisp vector SVG QR code via reportlab
        and returns a Base64 data URL (`data:image/svg+xml;base64,...`).
        """
        qr_widget = QrCodeWidget(upi_uri)
        bounds = qr_widget.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        size = 220.0
        drawing = Drawing(
            size,
            size,
            transform=[size / width, 0, 0, size / height, 0, 0],
        )
        drawing.add(qr_widget)
        svg_bytes = renderSVG.drawToString(drawing)
        if isinstance(svg_bytes, str):
            svg_bytes = svg_bytes.encode("utf-8")
        encoded = base64.b64encode(svg_bytes).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    async def get_wallet_overview(
        self, user: User, tenant: Tenant
    ) -> WalletOverviewResponse:
        """
        Balance + passbook totals. Read-only: a user without a wallet row yet
        sees ₹0.00; the row is created on the first write (recharge / debit).
        """
        wallet = await self.wallet_repo.get_wallet(
            user_id=user.id, tenant_id=tenant.id, for_update=False
        )
        summary_dict = await self.wallet_repo.get_wallet_summary(
            user_id=user.id, tenant_id=tenant.id
        )
        return WalletOverviewResponse(
            balance=round(float(wallet.balance), 2) if wallet else 0.0,
            currency="INR",
            wallet_config=self.resolve_wallet_config(tenant),
            summary=WalletSummary(**summary_dict),
        )

    @staticmethod
    def _resolve_ledger_scope(
        user: User, filter_user_id: Optional[uuid.UUID]
    ) -> Optional[uuid.UUID]:
        """
        Which wallet(s) a ledger read covers.

        Owner / Admin / Read-Only staff see every user's transactions in the tenant
        (optionally narrowed to `filter_user_id`); everyone else only sees their own.

        Returns:
            The user id to filter on, or None for the whole tenant.
        """
        if can_view_tenant_finance(user):
            return filter_user_id
        return user.id

    async def list_user_transactions(
        self,
        user: User,
        tenant: Tenant,
        tab: str = "all",
        page: int = 1,
        size: int = 20,
        filter_user_id: Optional[uuid.UUID] = None,
    ) -> Tuple[List[WalletTransaction], int]:
        """Paginated passbook (read-only; no wallet row is created here)."""
        return await self.wallet_repo.list_transactions(
            user_id=self._resolve_ledger_scope(user, filter_user_id),
            tenant_id=tenant.id,
            tab=tab,
            page=page,
            size=size,
        )

    async def create_upi_intent(
        self,
        user: User,
        tenant: Tenant,
        payload: UpiIntentRequest,
    ) -> UpiIntentResponse:
        assert_can_manage_finance_or_wallet(user, "create wallet recharge intents")
        if payload.amount < 1.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Minimum recharge amount is ₹1.00",
            )

        w_cfg = self.resolve_wallet_config(tenant)
        vpa = w_cfg["merchant_vpa"]
        if not vpa:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=self.UPI_NOT_CONFIGURED_DETAIL,
            )
        merchant_name = w_cfg["merchant_name"]
        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=user.id, tenant_id=tenant.id, for_update=False
        )
        amt = round(float(payload.amount), 2)

        txn_id = uuid.uuid4()
        short_id = str(txn_id)[:8].upper()
        receipt_no = wallet_receipt_number("REC", txn_id)

        upi_uri = (
            f"upi://pay?pa={quote(vpa)}&pn={quote(merchant_name)}"
            f"&am={amt:.2f}&cu=INR&tr={quote(receipt_no)}&tn={quote(f'WalletRecharge-{short_id}')}"
        )
        qr_svg_data_url = self._generate_qr_svg_data_url(upi_uri)

        txn = WalletTransaction(
            id=txn_id,
            wallet_id=wallet.id,
            tenant_id=tenant.id,
            user_id=user.id,
            txn_type=WalletTxnType.RECHARGE,
            service_category=WalletServiceCategory.RECHARGE,
            opening_balance=round(float(wallet.balance), 2),
            amount=amt,
            closing_balance=round(float(wallet.balance), 2),
            receipt_number=receipt_no,
            status=WalletTxnStatus.PENDING,
            remarks=f"UPI QR Recharge Intent ({vpa})",
            created_at=_utc_now_naive(),
        )
        await self.wallet_repo.create_transaction(txn)
        await self.wallet_repo.session.commit()

        return UpiIntentResponse(
            transaction_id=txn.id,
            upi_uri=upi_uri,
            qr_svg_data_url=qr_svg_data_url,
            merchant_vpa=vpa,
            merchant_name=merchant_name,
            amount=amt,
        )

    async def _complete_pending_recharge_txn(
        self,
        *,
        txn: WalletTransaction,
        wallet: UserWallet,
        utr_number: str,
        remarks_label: str = "UPI QR Payment Verified",
    ) -> Tuple[float, WalletTransaction]:
        """
        Atomically completes a PENDING UPI recharge transaction and credits
        the user's locked UserWallet row with a verified UTR or Admin reference.
        """
        resolved_utr = (utr_number or "").strip()
        if not resolved_utr:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid 12-digit UPI UTR reference is required to complete a recharge.",
            )

        recharge_amount = round(float(txn.amount), 2)
        opening_bal = round(float(wallet.balance), 2)
        closing_bal = round(opening_bal + recharge_amount, 2)

        wallet.balance = closing_bal
        wallet.updated_at = _utc_now_naive()
        self.wallet_repo.session.add(wallet)

        txn.opening_balance = opening_bal
        txn.closing_balance = closing_bal
        txn.utr_number = resolved_utr
        txn.receipt_number = txn.receipt_number or wallet_receipt_number("REC", txn.id)
        txn.status = WalletTxnStatus.COMPLETED
        txn.remarks = f"{remarks_label} (Ref: {resolved_utr})"
        self.wallet_repo.session.add(txn)

        try:
            await self.wallet_repo.session.commit()
            await self.wallet_repo.session.refresh(txn)
        except IntegrityError:
            await self.wallet_repo.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate UTR number '{resolved_utr}'.",
            )
        return closing_bal, txn

    async def check_upi_recharge_status(
        self,
        *,
        user: User,
        tenant: Tenant,
        transaction_id: uuid.UUID,
        auto_complete: Optional[bool] = None,
    ) -> UpiRechargeStatusResponse:
        """
        Polls the status of a UPI QR recharge intent (`GET /wallet/recharge/{id}/status`).
        Strictly returns COMPLETED only when verified via 12-digit UTR or Admin/Webhook settlement.
        """
        txn = await self.wallet_repo.get_transaction_by_id(
            txn_id=transaction_id, tenant_id=tenant.id
        )
        if not txn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="UPI recharge transaction not found.",
            )

        is_admin = user.role in (UserRole.admin, UserRole.owner)
        if not is_admin and txn.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot check another user's recharge transaction.",
            )

        if txn.status == WalletTxnStatus.COMPLETED:
            wallet = await self.wallet_repo.get_or_create_wallet(
                user_id=txn.user_id, tenant_id=tenant.id, for_update=False
            )
            return UpiRechargeStatusResponse(
                transaction_id=txn.id,
                status=txn.status,
                balance=round(float(wallet.balance), 2),
                transaction=WalletTransactionRead.model_validate(txn),
                auto_detected=True,
            )

        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=txn.user_id, tenant_id=tenant.id, for_update=False
        )
        return UpiRechargeStatusResponse(
            transaction_id=txn.id,
            status=txn.status,
            balance=round(float(wallet.balance), 2),
            transaction=WalletTransactionRead.model_validate(txn),
            auto_detected=False,
        )

    async def confirm_upi_recharge(
        self,
        *,
        user: User,
        tenant: Tenant,
        transaction_id: uuid.UUID,
        payload: Optional[UpiConfirmRequest] = None,
    ) -> UpiRechargeStatusResponse:
        """
        Records that the user clicked 'I Have Paid' on a UPI QR recharge intent.
        - A 12-digit numeric UTR is mandatory (A-14): without it two "I have paid" requests
          for one payment would get distinct references and dodge the duplicate-UTR rule.
        - Keeps `status = WalletTxnStatus.PENDING` (does NOT credit main `wallet.balance` yet).
        - Stores the UTR so `summary.pending_recharge` and the Admin Approval Queue show the
          pending amount awaiting Admin approval.
        """
        txn = await self.wallet_repo.get_transaction_by_id(
            txn_id=transaction_id, tenant_id=tenant.id
        )
        if not txn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="UPI recharge transaction not found.",
            )

        is_admin = user.role in (UserRole.admin, UserRole.owner)
        if not is_admin and txn.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot confirm another user's recharge transaction.",
            )

        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=txn.user_id, tenant_id=tenant.id, for_update=False
        )
        if txn.status == WalletTxnStatus.COMPLETED:
            return UpiRechargeStatusResponse(
                transaction_id=txn.id,
                status=txn.status,
                balance=round(float(wallet.balance), 2),
                transaction=WalletTransactionRead.model_validate(txn),
                auto_detected=True,
            )
        if txn.status == WalletTxnStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This recharge request was rejected and cannot be submitted.",
            )

        submitted_utr = (payload.utr_number or "").strip() if payload else ""
        if not UTR_PATTERN.match(submitted_utr):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=UTR_REQUIRED_DETAIL,
            )
        existing = await self.wallet_repo.get_transaction_by_utr(submitted_utr)
        if existing is not None and existing.id != txn.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate UTR number '{submitted_utr}'. This 12-digit UTR has already been submitted.",
            )
        resolved_ref = submitted_utr

        w_cfg = self.resolve_wallet_config(tenant)
        txn.utr_number = resolved_ref
        txn.status = WalletTxnStatus.PENDING
        txn.remarks = (
            f"Pending Admin Approval — User marked Paid "
            f"(Ref: {resolved_ref}, VPA: {w_cfg['merchant_vpa']})"
        )
        self.wallet_repo.session.add(txn)

        try:
            await self.wallet_repo.session.commit()
            await self.wallet_repo.session.refresh(txn)
        except IntegrityError:
            await self.wallet_repo.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate UTR number '{resolved_ref}'.",
            )

        await notify_wallet_recharge_status(
            merchant_email=user.email,
            amount_inr=float(txn.amount or 0.0),
            status_label="PENDING_APPROVAL",
            utr=resolved_ref,
            note=txn.remarks,
        )

        return UpiRechargeStatusResponse(
            transaction_id=txn.id,
            status=txn.status,
            balance=round(float(wallet.balance), 2),
            transaction=WalletTransactionRead.model_validate(txn),
            auto_detected=False,
        )

    async def approve_pending_recharge(
        self,
        *,
        admin_user: User,
        tenant: Tenant,
        transaction_id: uuid.UUID,
    ) -> UpiRechargeStatusResponse:
        """
        Admin-only action: Approves a PENDING recharge request and merges the pending
        amount into the user's main spendable `UserWallet.balance`.
        """
        if admin_user.role not in (UserRole.admin, UserRole.owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Tenant Admins can approve and merge pending wallet recharges.",
            )

        txn = await self.wallet_repo.get_transaction_by_id(
            txn_id=transaction_id, tenant_id=tenant.id
        )
        if not txn or txn.txn_type != WalletTxnType.RECHARGE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending recharge transaction not found.",
            )
        if txn.user_id == admin_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Maker-checker: you cannot approve your own recharge request. "
                    "Ask another Admin or the Owner to approve it."
                ),
            )

        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=txn.user_id, tenant_id=tenant.id, for_update=True
        )
        await self.wallet_repo.session.refresh(txn)

        if txn.status == WalletTxnStatus.COMPLETED:
            return UpiRechargeStatusResponse(
                transaction_id=txn.id,
                status=txn.status,
                balance=round(float(wallet.balance), 2),
                transaction=WalletTransactionRead.model_validate(txn),
                auto_detected=True,
            )
        if txn.status == WalletTxnStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve a recharge request that has already been rejected.",
            )
        if not UTR_PATTERN.match(txn.utr_number or ""):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This request has no 12-digit bank UTR, so it can't be matched to a payment. "
                    "Reject it and ask the merchant to submit the UTR."
                ),
            )

        resolved_ref = txn.utr_number
        closing_bal, completed_txn = await self._complete_pending_recharge_txn(
            txn=txn,
            wallet=wallet,
            utr_number=resolved_ref,
            remarks_label="Approved by Admin — Merged into Main Wallet",
        )
        owner_user = await self.wallet_repo.session.get(User, completed_txn.user_id)
        await notify_wallet_recharge_status(
            merchant_email=owner_user.email if owner_user else None,
            amount_inr=float(completed_txn.amount or 0.0),
            status_label="APPROVED",
            utr=resolved_ref,
            note=completed_txn.remarks,
        )
        return UpiRechargeStatusResponse(
            transaction_id=completed_txn.id,
            status=completed_txn.status,
            balance=closing_bal,
            transaction=WalletTransactionRead.model_validate(completed_txn),
            auto_detected=True,
        )

    async def reject_pending_recharge(
        self,
        *,
        admin_user: User,
        tenant: Tenant,
        transaction_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> UpiRechargeStatusResponse:
        """
        Admin-only action: Rejects a PENDING recharge request without crediting the wallet.
        The reason (A-15) is stored in `remarks`, which the merchant sees in the passbook.
        """
        if admin_user.role not in (UserRole.admin, UserRole.owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Tenant Admins can reject pending wallet recharges.",
            )

        txn = await self.wallet_repo.get_transaction_by_id(
            txn_id=transaction_id, tenant_id=tenant.id
        )
        if not txn or txn.txn_type != WalletTxnType.RECHARGE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending recharge transaction not found.",
            )

        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=txn.user_id, tenant_id=tenant.id, for_update=True
        )
        await self.wallet_repo.session.refresh(txn)

        if txn.status == WalletTxnStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reject a recharge transaction that has already been approved.",
            )

        txn.status = WalletTxnStatus.FAILED
        cleaned_reason = (reason or "").strip()
        txn.remarks = (
            f"{RECHARGE_REJECTED_REMARK_PREFIX}: {cleaned_reason}"
            if cleaned_reason
            else f"{RECHARGE_REJECTED_REMARK_PREFIX} (Ref: {txn.utr_number or 'N/A'})"
        )
        self.wallet_repo.session.add(txn)
        await self.wallet_repo.session.commit()
        await self.wallet_repo.session.refresh(txn)
        owner_user = await self.wallet_repo.session.get(User, txn.user_id)
        await notify_wallet_recharge_status(
            merchant_email=owner_user.email if owner_user else None,
            amount_inr=float(txn.amount or 0.0),
            status_label="REJECTED",
            utr=txn.utr_number,
            note=txn.remarks,
        )

        return UpiRechargeStatusResponse(
            transaction_id=txn.id,
            status=txn.status,
            balance=round(float(wallet.balance), 2),
            transaction=WalletTransactionRead.model_validate(txn),
            auto_detected=False,
        )

    async def list_tenant_pending_recharges(
        self,
        *,
        admin_user: User,
        tenant: Tenant,
    ) -> List[WalletTransactionRead]:
        """
        Admin-only action: Lists all PENDING recharge requests across the tenant
        where the user has clicked 'I Have Paid' (`utr_number IS NOT NULL`).
        """
        if admin_user.role not in (UserRole.admin, UserRole.owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Tenant Admins can view all tenant pending recharges.",
            )
        rows = await self.wallet_repo.list_pending_recharges_for_tenant(
            tenant_id=tenant.id
        )
        results: List[WalletTransactionRead] = []
        for txn in rows:
            dto = WalletTransactionRead.model_validate(txn)
            dto.user_email = getattr(txn, "user_email", None)
            results.append(dto)
        return results

    async def verify_utr_recharge(
        self,
        user: User,
        tenant: Tenant,
        payload: VerifyUtrRequest,
    ) -> VerifyUtrResponse:
        """
        Admin "approve with UTR": an Owner / Admin who sees the merchant's bank credit enters
        its 12-digit UTR against the MERCHANT's pending QR intent and the merchant's wallet is
        credited at once (B-06).

        There is no self-credit path any more: a `transaction_id` is required, it must be
        another user's intent (maker-checker), and the credited wallet is the intent owner's,
        never the caller's.

        Raises:
            HTTPException(400): bad UTR, no intent, amount mismatch.
            HTTPException(403): the admin's own intent.
            HTTPException(404/409): unknown intent, duplicate UTR or already completed.
        """
        cleaned_utr = (payload.utr_number or "").strip()
        if not UTR_PATTERN.match(cleaned_utr):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid UTR format. UTR number must be exactly 12 numeric digits.",
            )
        existing_utr_txn = await self.wallet_repo.get_transaction_by_utr(cleaned_utr)
        if existing_utr_txn is not None and existing_utr_txn.id != payload.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate UTR number '{cleaned_utr}'. This 12-digit UTR has already been processed.",
            )
        if payload.transaction_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Pick the merchant's recharge request this UTR pays. A wallet can't be "
                    "credited without a request."
                ),
            )

        txn = await self.wallet_repo.get_transaction_by_id(payload.transaction_id, tenant.id)
        if not txn or txn.txn_type != WalletTxnType.RECHARGE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="UPI recharge intent transaction not found.",
            )
        if txn.user_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Maker-checker: you cannot credit your own wallet. Ask another Admin or "
                    "the Owner to verify it."
                ),
            )
        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=txn.user_id, tenant_id=tenant.id, for_update=True
        )
        await self.wallet_repo.session.refresh(txn)
        if txn.status != WalletTxnStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This recharge request is no longer pending (already approved or rejected).",
            )
        if (
            payload.amount is not None
            and abs(round(float(payload.amount), 2) - round(float(txn.amount), 2)) > 0.01
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Recharge amount mismatch: QR intent was generated for ₹{float(txn.amount):.2f}, "
                    f"but ₹{float(payload.amount):.2f} was submitted."
                ),
            )

        closing_bal, completed_txn = await self._complete_pending_recharge_txn(
            txn=txn,
            wallet=wallet,
            utr_number=cleaned_utr,
            remarks_label="UPI Recharge Verified by Admin",
        )
        return VerifyUtrResponse(
            balance=closing_bal,
            transaction=WalletTransactionRead.model_validate(completed_txn),
        )

    async def record_admin_offline_credit(
        self,
        *,
        admin_user: User,
        tenant: Tenant,
        payload: AdminOfflineCreditRequest,
    ) -> VerifyUtrResponse:
        """
        Owner/Admin manual wallet credit when a customer sends money offline (#558 3b).
        Immediately credits the target user's wallet as a COMPLETED RECHARGE transaction
        with an official Wallet Advance Receipt Voucher (`REC-...`).
        """
        if admin_user.role not in (UserRole.admin, UserRole.owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Tenant Owners and Admins can record offline wallet credits.",
            )
        target_user = await self.wallet_repo.get_tenant_user(
            tenant_id=tenant.id,
            user_id=payload.user_id,
            user_email=payload.user_email,
        )
        if target_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target customer account not found in this tenant.",
            )

        cleaned_ref = (payload.utr_number or "").strip()
        if len(cleaned_ref) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Enter a valid bank reference, UTR, or receipt number (at least 4 characters).",
            )
        existing_txn = await self.wallet_repo.get_transaction_by_utr(cleaned_ref)
        if existing_txn is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate payment reference '{cleaned_ref}'. This reference has already been credited.",
            )

        credit_amount = round(float(payload.amount), 2)
        if credit_amount < 1.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Offline credit amount must be at least ₹1.00.",
            )

        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=target_user.id, tenant_id=tenant.id, for_update=True
        )
        opening_bal = round(float(wallet.balance), 2)
        closing_bal = round(opening_bal + credit_amount, 2)
        wallet.balance = closing_bal
        wallet.updated_at = _utc_now_naive()
        self.wallet_repo.session.add(wallet)

        txn_id = uuid.uuid4()
        method_label = (payload.payment_method or "Bank Transfer").strip() or "Bank Transfer"
        cleaned_notes = (payload.notes or "").strip()
        notes_suffix = f" — {cleaned_notes}" if cleaned_notes else ""
        remarks = (
            f"Offline Credit ({method_label}) recorded by {admin_user.email} "
            f"(Ref: {cleaned_ref}){notes_suffix}"
        )
        txn = WalletTransaction(
            id=txn_id,
            wallet_id=wallet.id,
            tenant_id=tenant.id,
            user_id=target_user.id,
            txn_type=WalletTxnType.RECHARGE,
            service_category=WalletServiceCategory.RECHARGE,
            opening_balance=opening_bal,
            amount=credit_amount,
            closing_balance=closing_bal,
            utr_number=cleaned_ref,
            receipt_number=wallet_receipt_number("REC", txn_id),
            status=WalletTxnStatus.COMPLETED,
            remarks=remarks,
            created_at=_utc_now_naive(),
        )
        self.wallet_repo.session.add(txn)
        try:
            await self.wallet_repo.session.commit()
            await self.wallet_repo.session.refresh(txn)
        except IntegrityError:
            await self.wallet_repo.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate payment reference '{cleaned_ref}'.",
            )

        await notify_wallet_recharge_status(
            merchant_email=target_user.email,
            amount_inr=credit_amount,
            status_label="APPROVED",
            utr=cleaned_ref,
            note=remarks,
        )
        dto = WalletTransactionRead.model_validate(txn)
        dto.user_email = target_user.email
        return VerifyUtrResponse(balance=closing_bal, transaction=dto)

    async def deduct_shipment_spend(
        self,
        *,
        user_id: uuid.UUID,
        tenant: Tenant,
        shipment: PickupRequest,
        amount: float,
        is_b2b: bool,
    ) -> WalletTransaction:
        """
        Atomically checks Finlock (when enabled in Tenant.settings['wallet_config'])
        and deducts `total_logistics_cost` (`SPEND`) from the user's wallet.
        """
        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=user_id, tenant_id=tenant.id, for_update=True
        )
        w_cfg = self.resolve_wallet_config(tenant)
        strict_finlock = bool(w_cfg.get("strict_finlock", False))
        min_required_floor = (
            float(w_cfg["min_wallet_balance_b2b"])
            if is_b2b
            else float(w_cfg["min_wallet_balance_b2c"])
        )

        spend_amt = round(float(amount), 2)
        opening_bal = round(float(wallet.balance), 2)
        is_postpaid = (
            shipment.payment_details is not None
            and shipment.payment_details.freight_payment_mode == FreightPaymentMode.POSTPAID
        )

        if strict_finlock and not is_postpaid:
            required_threshold = max(spend_amt, min_required_floor)
            if opening_bal < required_threshold:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Insufficient wallet balance (₹{opening_bal:.2f}) - Finlock active. "
                        f"Minimum required balance is ₹{required_threshold:.2f} to book this shipment. "
                        "Please recharge your wallet."
                    ),
                )

        closing_bal = round(opening_bal - spend_amt, 2)
        wallet.balance = closing_bal
        wallet.updated_at = _utc_now_naive()
        self.wallet_repo.session.add(wallet)

        txn = WalletTransaction(
            id=uuid.uuid4(),
            wallet_id=wallet.id,
            tenant_id=tenant.id,
            user_id=user_id,
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            txn_type=WalletTxnType.SPEND,
            service_category=(
                WalletServiceCategory.B2B
                if is_b2b
                else WalletServiceCategory.B2C
            ),
            opening_balance=opening_bal,
            amount=spend_amt,
            closing_balance=closing_bal,
            receipt_number=wallet_receipt_number("INV", shipment.id),
            status=WalletTxnStatus.COMPLETED,
            remarks=f"Freight charge deducted for {shipment.tracking_id}",
            created_at=_utc_now_naive(),
        )
        self.wallet_repo.session.add(txn)
        await self.wallet_repo.session.flush()
        return txn

    async def get_net_debited_for_shipment(
        self,
        *,
        shipment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> float:
        """
        Calculates the exact net amount currently debited from the wallet for a shipment
        via `net_debited(txns)` (SPEND + WEIGHT_AUDIT_DEBIT + RTO_FREIGHT - REFUND - CHARGE_REVERSAL).
        Prevents refunding more than was ever paid or refunding legacy unpaid shipments.
        """
        txns = await self.wallet_repo.get_transactions_by_shipment_id(
            shipment_id=shipment_id, tenant_id=tenant_id
        )
        return round(max(0.0, float(net_debited(txns))), 2)

    async def refund_shipment_spend(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        shipment: PickupRequest,
        amount: float,
        is_b2b: bool,
        remarks: Optional[str] = None,
    ) -> Optional[WalletTransaction]:
        """
        Atomically refunds the net debited freight back into the shipment
        creator's wallet upon cancellation (or downward edit) of a PREPAID shipment.
        Never refunds more than was actually debited from the wallet for this shipment.
        """
        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=user_id, tenant_id=tenant_id, for_update=True
        )
        net_debited = await self.get_net_debited_for_shipment(
            shipment_id=shipment.id, tenant_id=tenant_id
        )
        if net_debited <= 0:
            existing_refund = await self.wallet_repo.get_transaction_by_shipment_id(
                shipment_id=shipment.id,
                tenant_id=tenant_id,
                txn_type=WalletTxnType.REFUND,
            )
            return existing_refund

        requested_amt = round(float(amount), 2)
        if requested_amt <= 0:
            # A zero / negative request is a caller bug, never "refund everything" (plan B12).
            return None
        refund_amt = round(min(requested_amt, net_debited), 2)
        if refund_amt <= 0:
            return None

        opening_bal = round(float(wallet.balance), 2)
        closing_bal = round(opening_bal + refund_amt, 2)

        wallet.balance = closing_bal
        wallet.updated_at = _utc_now_naive()
        self.wallet_repo.session.add(wallet)

        txn_uuid = uuid.uuid4()
        txn = WalletTransaction(
            id=txn_uuid,
            wallet_id=wallet.id,
            tenant_id=tenant_id,
            user_id=user_id,
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            txn_type=WalletTxnType.REFUND,
            service_category=(
                WalletServiceCategory.B2B
                if is_b2b
                else WalletServiceCategory.B2C
            ),
            opening_balance=opening_bal,
            amount=refund_amt,
            closing_balance=closing_bal,
            receipt_number=wallet_receipt_number("CN", txn_uuid),
            status=WalletTxnStatus.COMPLETED,
            remarks=remarks or f"Freight refund credited for cancelled shipment {shipment.tracking_id}",
            created_at=_utc_now_naive(),
        )
        self.wallet_repo.session.add(txn)
        await self.wallet_repo.session.flush()
        return txn

    async def debit_exception_charge(
        self,
        *,
        user_id: uuid.UUID,
        tenant: Tenant,
        shipment: PickupRequest,
        amount: float,
        txn_type: WalletTxnType,
        is_b2b: bool,
    ) -> WalletTransaction:
        """
        Debits an exception charge (freight collection or additional charges)
        that the merchant acknowledged on an on-hold shipment.

        Locks the wallet row (`SELECT ... FOR UPDATE`) and writes an immutable
        ledger entry with a receipt number. Never blocked by Finlock: post-booking
        charges may take the wallet negative (plan §2.0, decision D18).

        Args:
            user_id: Shipment creator whose wallet is debited.
            tenant: Owning tenant.
            shipment: The on-hold shipment the charge belongs to.
            amount: Charge in INR (> 0).
            txn_type: FREIGHT_COLLECTION or ADDITIONAL_CHARGE.
            is_b2b: Ledger service category (B2B vs B2C).

        Returns:
            The persisted (flushed, not committed) WalletTransaction.
        """
        if txn_type not in self.EXCEPTION_CHARGE_TXN_PREFIXES:
            raise ValueError(f"Unsupported exception charge type: {txn_type}")
        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=user_id, tenant_id=tenant.id, for_update=True
        )
        debit_amt = round(float(amount), 2)
        opening_bal = round(float(wallet.balance), 2)
        closing_bal = round(opening_bal - debit_amt, 2)
        wallet.balance = closing_bal
        wallet.updated_at = _utc_now_naive()
        self.wallet_repo.session.add(wallet)

        txn_uuid = uuid.uuid4()
        prefix = self.EXCEPTION_CHARGE_TXN_PREFIXES[txn_type]
        label = "Freight collection" if txn_type == WalletTxnType.FREIGHT_COLLECTION else "Additional charges"
        txn = WalletTransaction(
            id=txn_uuid,
            wallet_id=wallet.id,
            tenant_id=tenant.id,
            user_id=user_id,
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            txn_type=txn_type,
            service_category=(
                WalletServiceCategory.B2B if is_b2b else WalletServiceCategory.B2C
            ),
            opening_balance=opening_bal,
            amount=debit_amt,
            closing_balance=closing_bal,
            receipt_number=wallet_receipt_number(prefix, txn_uuid),
            status=WalletTxnStatus.COMPLETED,
            remarks=f"{label} acknowledged for {shipment.tracking_id}",
            created_at=_utc_now_naive(),
        )
        self.wallet_repo.session.add(txn)
        await self.wallet_repo.session.flush()
        return txn

    async def _resolve_cod_settlement_owner(
        self, user: User, tenant: Tenant, merchant_user_id: Optional[uuid.UUID]
    ) -> uuid.UUID:
        """
        Whose delivered COD a settle-to-wallet call pays out.

        Only Owner / Admin may settle (a customer is paid in the finance team's remittance
        cycle, coordinator decision 2026-11-01); they settle their own bookings or, with
        `merchant_user_id`, a merchant's COD into that merchant's wallet.

        Raises:
            HTTPException(403): a customer or a non-finance staff role.
            HTTPException(404): `merchant_user_id` is not a user of this tenant.
        """
        if user.role == UserRole.customer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=CUSTOMER_COD_SETTLE_DETAIL
            )
        assert_can_manage_finance_or_wallet(user, "settle COD to wallet")
        if merchant_user_id is None or merchant_user_id == user.id:
            return user.id
        merchant = await self.wallet_repo.session.get(User, merchant_user_id)
        if merchant is None or merchant.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=COD_MERCHANT_NOT_FOUND_DETAIL
            )
        return merchant.id

    async def settle_cod_to_wallet(
        self,
        user: User,
        tenant: Tenant,
        merchant_user_id: Optional[uuid.UUID] = None,
    ) -> CodSettlementResponse:
        """
        Credits delivered, not-yet-remitted COD into a wallet (one COD_SETTLEMENT txn per
        AWB plus a `WALLET-COD-*` remittance record). See `_resolve_cod_settlement_owner`
        for who may call it and whose COD it settles.
        """
        owner_id = await self._resolve_cod_settlement_owner(user, tenant, merchant_user_id)
        wallet = await self.wallet_repo.get_or_create_wallet(
            user_id=owner_id, tenant_id=tenant.id, for_update=True
        )
        # A-24: the first read takes the row locks; the second, a new statement under those
        # locks, sees a bank remittance that committed while we waited (the joined
        # payment_details row is not re-checked by the lock), so no AWB is paid twice.
        await self.wallet_repo.get_unsettled_completed_cod_shipments(
            user_id=owner_id, tenant_id=tenant.id
        )
        shipments = await self.wallet_repo.get_unsettled_completed_cod_shipments(
            user_id=owner_id, tenant_id=tenant.id
        )

        created_txns: List[WalletTransactionRead] = []
        settled_breakdown: List[dict] = []
        total_settled = 0.0

        for s in shipments:
            if not s.payment_details or s.payment_details.cod_amount <= 0:
                continue
            existing_cod = await self.wallet_repo.get_transaction_by_shipment_id(
                shipment_id=s.id,
                tenant_id=tenant.id,
                txn_type=WalletTxnType.COD_SETTLEMENT,
            )
            if existing_cod is not None:
                s.payment_details.cod_remittance_status = (
                    CodRemittanceStatus.REMITTED
                )
                self.wallet_repo.session.add(s.payment_details)
                continue

            amt = cod_payout_amount(s.payment_details)
            if amt <= 0:
                # Everything collected belongs to the carrier (e.g. TO_PAY freight only).
                s.payment_details.cod_remittance_status = CodRemittanceStatus.REMITTED
                self.wallet_repo.session.add(s.payment_details)
                continue
            opening_bal = round(float(wallet.balance), 2)
            closing_bal = round(opening_bal + amt, 2)
            wallet.balance = closing_bal
            wallet.updated_at = _utc_now_naive()

            s.payment_details.cod_remittance_status = (
                CodRemittanceStatus.REMITTED
            )
            self.wallet_repo.session.add(s.payment_details)

            txn = WalletTransaction(
                id=uuid.uuid4(),
                wallet_id=wallet.id,
                tenant_id=tenant.id,
                user_id=owner_id,
                shipment_id=s.id,
                tracking_id=s.tracking_id,
                txn_type=WalletTxnType.COD_SETTLEMENT,
                service_category=(
                    WalletServiceCategory.B2B
                    if is_b2b_shipment(s)
                    else WalletServiceCategory.B2C
                ),
                opening_balance=opening_bal,
                amount=amt,
                closing_balance=closing_bal,
                receipt_number=wallet_receipt_number("COD", s.id),
                status=WalletTxnStatus.COMPLETED,
                remarks=f"Early COD Remittance for {s.tracking_id}",
                created_at=_utc_now_naive(),
            )
            self.wallet_repo.session.add(txn)
            await self.wallet_repo.session.flush()
            created_txns.append(WalletTransactionRead.model_validate(txn))
            settled_breakdown.append(
                {
                    "shipment_id": str(s.id),
                    "tracking_id": s.tracking_id or "",
                    "order_reference_id": s.order_reference_id or "",
                    "amount_collected": amt,
                }
            )
            total_settled = round(total_settled + amt, 2)

        if settled_breakdown:
            proc_date = _utc_now_naive().date()
            remit_number = (
                f"R471378{proc_date.strftime('%Y%m%d')}{uuid.uuid4().int % 100000:05d}"
            )
            remittance_row = CodRemittance(
                tenant_id=tenant.id,
                merchant_user_id=owner_id,
                remittance_number=remit_number,
                processed_date=proc_date,
                bank_utr=f"{WALLET_COD_UTR_PREFIX}{str(uuid.uuid4())[:8].upper()}",
                state=RemittanceState.COMPLETED.value,
                total_remittance=total_settled,
                total_orders=len(settled_breakdown),
                shipment_breakdown=settled_breakdown,
            )
            self.wallet_repo.session.add(remittance_row)

        self.wallet_repo.session.add(wallet)
        await self.wallet_repo.session.commit()

        return CodSettlementResponse(
            settled_count=len(created_txns),
            settled_amount=total_settled,
            new_balance=round(float(wallet.balance), 2),
            transactions=created_txns,
        )

    async def export_transactions_csv(
        self,
        user: User,
        tenant: Tenant,
        filter_user_id: Optional[uuid.UUID] = None,
    ) -> io.StringIO:
        txns = await self.wallet_repo.list_all_user_transactions(
            user_id=self._resolve_ledger_scope(user, filter_user_id),
            tenant_id=tenant.id,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Transaction ID",
                "Receipt / Invoice No",
                "Date (UTC)",
                "User Email",
                "Type",
                "Service Category",
                "AWB / Tracking ID",
                "UTR Number",
                "Opening Balance (INR)",
                "Amount (INR)",
                "Closing Balance (INR)",
                "Status",
                "Remarks",
            ]
        )
        for t in txns:
            txn_type_s = str(t.txn_type.value if hasattr(t.txn_type, "value") else t.txn_type)
            svc_cat_s = str(
                t.service_category.value
                if hasattr(t.service_category, "value")
                else t.service_category
            )
            status_s = str(t.status.value if hasattr(t.status, "value") else t.status)
            writer.writerow(
                [
                    str(t.id),
                    t.receipt_number,
                    t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    getattr(t, "user_email", None) or "",
                    txn_type_s,
                    svc_cat_s,
                    t.tracking_id or "",
                    t.utr_number or "",
                    f"{t.opening_balance:.2f}",
                    f"{t.amount:.2f}",
                    f"{t.closing_balance:.2f}",
                    status_s,
                    t.remarks or "",
                ]
            )
        output.seek(0)
        return output

    async def audit_tenant_integrity(
        self,
        user: User,
        tenant: Tenant,
    ) -> WalletIntegrityAuditResponse:
        """Delegates to `IntegrityAuditService` (plan B11)."""
        return await IntegrityAuditService(self.wallet_repo).audit_tenant_integrity(
            user=user, tenant=tenant
        )


def get_wallet_service(
    session: AsyncSession = Depends(get_session),
) -> WalletService:
    return WalletService(WalletRepository(session))

