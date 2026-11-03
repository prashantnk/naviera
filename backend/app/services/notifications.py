"""
Minimal transactional email notifier for MVP critical events (I-02).

Dispatches transactional notifications for:
1. Delivery / Pickup Exception (NDR) raised (`notify_ndr_raised`)
2. Wallet recharge submitted / approved / rejected (`notify_wallet_recharge_status`)
3. Weight discrepancy debit recorded (`notify_weight_debit`)

When `SMTP_HOST` is configured in the environment, messages are sent over SMTP in a
background thread with a short timeout; otherwise they are logged as structured
`transactional_email_dispatched` records and retained in an in-memory ring buffer
(`RECENT_NOTIFICATIONS`) for audit/testing. Notification errors are caught and logged
so they never roll back a committed financial or operational transaction.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Deque, List, Optional

logger = logging.getLogger(__name__)

MAX_RECENT_NOTIFICATIONS = 200
SMTP_TIMEOUT_SECONDS = 5.0
DEFAULT_FROM_EMAIL = "no-reply@naviera.com"


@dataclass(frozen=True)
class TransactionalNotification:
    """Immutable record of a dispatched transactional email."""

    event_type: str
    to_email: str
    subject: str
    body: str
    dispatched_at: str
    delivered_via: str


RECENT_NOTIFICATIONS: Deque[TransactionalNotification] = deque(
    maxlen=MAX_RECENT_NOTIFICATIONS
)


def get_recent_notifications() -> List[TransactionalNotification]:
    """Returns a snapshot of recently dispatched transactional notifications."""
    return list(RECENT_NOTIFICATIONS)


def clear_recent_notifications() -> None:
    """Clears the in-memory notification ring buffer (used by unit tests)."""
    RECENT_NOTIFICATIONS.clear()


def _send_smtp_sync(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: Optional[str],
    smtp_password: Optional[str],
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    """Sends a plain-text email over SMTP with TLS when credentials are provided."""
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        if smtp_user and smtp_password:
            server.starttls()
            server.login(smtp_user, smtp_password)
        server.send_message(msg)


async def send_transactional_email(
    *,
    to_email: Optional[str],
    subject: str,
    body: str,
    event_type: str,
) -> Optional[TransactionalNotification]:
    """
    Sends (or logs) a transactional email notification without raising on failure.
    """
    recipient = (to_email or "").strip()
    if not recipient or "@" not in recipient:
        return None

    smtp_host = (os.getenv("SMTP_HOST") or "").strip()
    from_email = (os.getenv("SMTP_FROM_EMAIL") or DEFAULT_FROM_EMAIL).strip()
    delivered_via = "log"

    if smtp_host:
        smtp_port = int(os.getenv("SMTP_PORT") or "587")
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")
        try:
            await asyncio.to_thread(
                _send_smtp_sync,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
                from_email=from_email,
                to_email=recipient,
                subject=subject,
                body=body,
            )
            delivered_via = "smtp"
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "SMTP dispatch failed for event=%s to=%s: %s",
                event_type,
                recipient,
                exc,
            )
            delivered_via = "log_fallback"

    record = TransactionalNotification(
        event_type=event_type,
        to_email=recipient,
        subject=subject,
        body=body,
        dispatched_at=datetime.now(timezone.utc).isoformat(),
        delivered_via=delivered_via,
    )
    RECENT_NOTIFICATIONS.append(record)
    logger.info(
        "transactional_email_dispatched event=%s to=%s via=%s subject=%r",
        event_type,
        recipient,
        delivered_via,
        subject,
    )
    return record


async def notify_ndr_raised(
    *,
    merchant_email: Optional[str],
    tracking_id: Optional[str],
    reason: Optional[str],
    remark: Optional[str] = None,
) -> Optional[TransactionalNotification]:
    """Notifies the merchant that an NDR / pickup exception requires their action."""
    awb = tracking_id or "Shipment"
    reason_label = (reason or "EXCEPTION").replace("_", " ")
    subject = f"[Action Required] Delivery Exception on {awb} ({reason_label})"
    lines = [
        f"A delivery/pickup exception ({reason_label}) has been recorded on AWB {awb}.",
    ]
    if remark:
        lines.append(f"Field remark: {remark}")
    lines.append(
        "Please sign in to your dashboard and open Exceptions (NDR) to submit "
        "Re-attempt or Return-to-Origin instructions."
    )
    return await send_transactional_email(
        to_email=merchant_email,
        subject=subject,
        body="\n\n".join(lines),
        event_type="NDR_RAISED",
    )


async def notify_wallet_recharge_status(
    *,
    merchant_email: Optional[str],
    amount_inr: float,
    status_label: str,
    utr: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[TransactionalNotification]:
    """Notifies the merchant when a wallet recharge is submitted, approved, or rejected."""
    clean_status = status_label.strip().upper()
    ref_suffix = f" (UTR: {utr})" if utr else ""
    subject = f"Wallet Recharge {clean_status}: ₹{amount_inr:,.2f}{ref_suffix}"
    lines = [
        f"Your wallet recharge of ₹{amount_inr:,.2f}{ref_suffix} is now {clean_status}.",
    ]
    if note:
        lines.append(f"Details: {note}")
    return await send_transactional_email(
        to_email=merchant_email,
        subject=subject,
        body="\n\n".join(lines),
        event_type=f"WALLET_RECHARGE_{clean_status}",
    )


async def notify_weight_debit(
    *,
    merchant_email: Optional[str],
    tracking_id: Optional[str],
    old_weight_kg: float,
    new_weight_kg: float,
    debit_inr: float,
) -> Optional[TransactionalNotification]:
    """Notifies the merchant when a hub/pickup weight measurement debits their wallet."""
    awb = tracking_id or "Shipment"
    subject = f"Weight Adjustment Debit on {awb}: ₹{debit_inr:,.2f}"
    body = (
        f"AWB {awb} was measured at {new_weight_kg:g} kg "
        f"(declared: {old_weight_kg:g} kg).\n\n"
        f"An upward freight adjustment of ₹{debit_inr:,.2f} has been applied to your wallet. "
        "If you believe this measurement is incorrect, you can raise a claim under "
        "Disputes -> Weight Mismatch."
    )
    return await send_transactional_email(
        to_email=merchant_email,
        subject=subject,
        body=body,
        event_type="WEIGHT_DEBIT",
    )
