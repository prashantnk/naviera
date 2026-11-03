import io
from datetime import datetime, timezone
from typing import List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from app.models.delhivery_modules import BillingInvoice
from app.models.manifests import Manifest
from app.models.pickups import Address, PickupRequest
from app.models.tenants import Tenant, User
from app.models.wallet import WalletTransaction, WalletTxnType
from app.services.delhivery_modules import (
    render_gst_document,
    resolve_supplier_gst_profile,
)
from app.services.wallet import IST

RECEIPT_TIMESTAMP_FORMAT = "%d %b %Y, %I:%M %p IST"
WALLET_RECEIPT_FOOTER = (
    "Computer generated wallet receipt (not a tax document). The GST tax invoice, "
    "credit and debit notes are under Finances > Invoices."
)


class ReceiptPdfGenerator:
    """
    Generates printable A4 PDF documents using reportlab:
    1. Wallet Transaction Receipt / Credit Note / Debit Receipt (`SAC 996812`)
    2. Shipment GST Tax Invoice (`SAC 996812`), printing the GST register row
       (same number and CGST+SGST vs IGST split as `/finances/invoices`)
    3. Fleet Manifest Driver Run-Sheet PDF
    """

    SAC_CODE = "996812"

    @classmethod
    def _resolve_tenant_gstin(cls, tenant: Tenant) -> str:
        """Supplier GSTIN strictly from the tenant's own settings ("Not Configured" if unset)."""
        return resolve_supplier_gst_profile(tenant).gstin

    @staticmethod
    def _enum_str(val) -> str:
        return str(val.value if hasattr(val, "value") else val)

    @classmethod
    def generate_wallet_receipt_pdf(
        cls,
        txn: WalletTransaction,
        tenant: Tenant,
        user: User,
        shipment: Optional[PickupRequest] = None,
    ) -> io.BytesIO:
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        gstin = cls._resolve_tenant_gstin(tenant)
        txn_type_str = cls._enum_str(txn.txn_type)
        service_cat_str = cls._enum_str(txn.service_category)
        status_str = cls._enum_str(txn.status)

        doc_title = "WALLET PAYMENT RECEIPT"
        if txn_type_str == WalletTxnType.REFUND.value:
            doc_title = "WALLET REFUND RECEIPT"
        elif txn_type_str in (
            WalletTxnType.SPEND.value,
            WalletTxnType.WEIGHT_AUDIT_DEBIT.value,
            WalletTxnType.FREIGHT_COLLECTION.value,
            WalletTxnType.ADDITIONAL_CHARGE.value,
        ):
            doc_title = "WALLET DEBIT RECEIPT"

        # Header Block
        c.setFont("Helvetica-Bold", 16)
        c.drawString(0.75 * inch, height - 0.85 * inch, tenant.name.upper())
        c.setFont("Helvetica", 10)
        c.drawString(
            0.75 * inch,
            height - 1.05 * inch,
            f"GSTIN: {gstin}  |  HSN/SAC Code: {cls.SAC_CODE} ( Courier & Freight Services )",
        )

        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(width - 0.75 * inch, height - 0.85 * inch, doc_title)
        c.setFont("Helvetica", 10)
        c.drawRightString(
            width - 0.75 * inch,
            height - 1.05 * inch,
            f"Receipt / Ref No: {txn.receipt_number}",
        )

        c.line(0.75 * inch, height - 1.25 * inch, width - 0.75 * inch, height - 1.25 * inch)

        # Metadata Section
        y = height - 1.6 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.75 * inch, y, "Customer Account:")
        c.setFont("Helvetica", 10)
        c.drawString(2.3 * inch, y, user.email)

        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.75 * inch, y, "Transaction ID:")
        c.setFont("Helvetica", 10)
        c.drawString(2.3 * inch, y, str(txn.id))

        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.75 * inch, y, "Transaction Date:")
        c.setFont("Helvetica", 10)
        c.drawString(2.3 * inch, y, cls._ist_timestamp(txn.created_at))

        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.75 * inch, y, "Transaction Type:")
        c.setFont("Helvetica", 10)
        c.drawString(
            2.3 * inch,
            y,
            f"{txn_type_str} ({service_cat_str}) - Status: {status_str}",
        )

        if txn.utr_number:
            y -= 0.25 * inch
            c.setFont("Helvetica-Bold", 10)
            c.drawString(0.75 * inch, y, "Bank / UPI UTR:")
            c.setFont("Helvetica", 10)
            c.drawString(2.3 * inch, y, txn.utr_number)

        tracking_id = txn.tracking_id or (shipment.tracking_id if shipment else None)
        if tracking_id:
            y -= 0.25 * inch
            c.setFont("Helvetica-Bold", 10)
            c.drawString(0.75 * inch, y, "AWB / Tracking ID:")
            c.setFont("Helvetica", 10)
            c.drawString(2.3 * inch, y, tracking_id)

        if txn.remarks:
            y -= 0.25 * inch
            c.setFont("Helvetica-Bold", 10)
            c.drawString(0.75 * inch, y, "Remarks:")
            c.setFont("Helvetica", 10)
            c.drawString(2.3 * inch, y, txn.remarks[:80])

        # Wallet Balance Ledger Summary
        y -= 0.45 * inch
        c.line(0.75 * inch, y + 0.15 * inch, width - 0.75 * inch, y + 0.15 * inch)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(0.75 * inch, y, "Wallet Balance Ledger Summary")

        y -= 0.3 * inch
        c.setFont("Helvetica", 10)
        c.drawString(0.75 * inch, y, "Opening Wallet Balance:")
        c.drawRightString(width - 0.75 * inch, y, f"INR {txn.opening_balance:,.2f}")

        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 10)
        sign = (
            "+"
            if txn_type_str
            in (
                WalletTxnType.RECHARGE.value,
                WalletTxnType.REFUND.value,
                WalletTxnType.COD_SETTLEMENT.value,
            )
            else "-"
        )
        c.drawString(0.75 * inch, y, f"Transaction Amount ({txn_type_str}):")
        c.drawRightString(width - 0.75 * inch, y, f"{sign} INR {txn.amount:,.2f}")

        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 11)
        c.drawString(0.75 * inch, y, "Closing Wallet Balance:")
        c.drawRightString(width - 0.75 * inch, y, f"INR {txn.closing_balance:,.2f}")

        # The live freight breakdown is NOT printed (C-04): it changes after a re-weigh,
        # while the issued GST documents (Finances > Invoices) are frozen at issue.
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(0.75 * inch, 0.75 * inch, WALLET_RECEIPT_FOOTER)

        c.showPage()
        c.save()
        buffer.seek(0)
        return buffer

    @staticmethod
    def _ist_timestamp(created_at: datetime) -> str:
        """A naive-UTC ledger timestamp shown in IST, e.g. "30 Oct 2026, 05:31 PM IST"."""
        aware = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        return aware.astimezone(IST).strftime(RECEIPT_TIMESTAMP_FORMAT)

    @classmethod
    def generate_shipment_invoice_pdf(
        cls,
        shipment: PickupRequest,
        tenant: Tenant,
        user: User,
        invoice: BillingInvoice,
        txn: Optional[WalletTransaction] = None,
    ) -> io.BytesIO:
        """
        Shipment GST tax invoice: the SAME renderer and stored register row as
        `/finances/invoices/{id}/pdf` (C-04), so one invoice number has one layout and
        never changes after issue. `shipment`, `user` and `txn` are accepted for the
        existing endpoint signature but deliberately not printed (they are live data).
        """
        return render_gst_document(invoice, tenant)

    @classmethod
    def generate_manifest_runsheet_pdf(
        cls,
        manifest: Manifest,
        tenant: Tenant,
        pickup_address: Optional[Address],
        shipments: List[PickupRequest],
    ) -> io.BytesIO:
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        c.setFont("Helvetica-Bold", 16)
        c.drawString(
            0.75 * inch,
            height - 0.85 * inch,
            f"{tenant.name.upper()} - DRIVER PICKUP RUN-SHEET",
        )
        c.setFont("Helvetica", 10)
        c.drawString(
            0.75 * inch,
            height - 1.08 * inch,
            f"Manifest ID: {manifest.id}  |  Status: {cls._enum_str(manifest.status)}",
        )
        c.drawRightString(
            width - 0.75 * inch,
            height - 1.08 * inch,
            f"Scheduled: {manifest.scheduled_date} ({cls._enum_str(manifest.time_slot)})",
        )

        c.line(0.75 * inch, height - 1.25 * inch, width - 0.75 * inch, height - 1.25 * inch)

        y = height - 1.55 * inch
        c.setFont("Helvetica-Bold", 10)
        wh_label = (
            f"{pickup_address.name} - {pickup_address.address_line1}, {pickup_address.city} ({pickup_address.pincode})"
            if pickup_address
            else f"Warehouse ID: {manifest.pickup_address_id}"
        )
        c.drawString(0.75 * inch, y, f"Pickup Location: {wh_label}")

        y -= 0.25 * inch
        total_weight = sum(
            (s.payment_details.chargeable_weight if s.payment_details else 0.0)
            for s in shipments
        )
        c.setFont("Helvetica", 10)
        c.drawString(
            0.75 * inch,
            y,
            f"Total AWBs: {len(shipments)}  |  Declared Total Boxes: {manifest.total_boxes}  |  Total Chargeable Weight: {total_weight:.2f} KG",
        )

        # Table Header
        y -= 0.4 * inch
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.75 * inch, y, "AWB / LRN")
        c.drawString(2.3 * inch, y, "Service")
        c.drawString(3.6 * inch, y, "Boxes")
        c.drawString(4.4 * inch, y, "Weight (KG)")
        c.drawString(5.5 * inch, y, "Status")
        c.line(0.75 * inch, y - 0.08 * inch, width - 0.75 * inch, y - 0.08 * inch)

        y -= 0.28 * inch
        c.setFont("Helvetica", 9)
        for s in shipments:
            box_cnt = sum((p.box_count or 1) for p in (s.packages or [])) or (
                s.estimated_box_count or 1
            )
            wt = s.payment_details.chargeable_weight if s.payment_details else 0.0
            c.drawString(0.75 * inch, y, str(s.tracking_id or s.id))
            c.drawString(2.3 * inch, y, cls._enum_str(s.service_type))
            c.drawString(3.6 * inch, y, str(box_cnt))
            c.drawString(4.4 * inch, y, f"{wt:.2f}")
            c.drawString(5.5 * inch, y, cls._enum_str(s.status))
            y -= 0.22 * inch
            if y < 1.8 * inch:
                c.showPage()
                y = height - 1.0 * inch

        # Driver Signature Block
        c.line(0.75 * inch, 1.35 * inch, 3.2 * inch, 1.35 * inch)
        c.line(width - 3.2 * inch, 1.35 * inch, width - 0.75 * inch, 1.35 * inch)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.75 * inch, 1.15 * inch, "Warehouse Dispatcher Signature & Stamp")
        c.drawString(width - 3.2 * inch, 1.15 * inch, "Driver / Field Executive Signature")

        c.showPage()
        c.save()
        buffer.seek(0)
        return buffer
