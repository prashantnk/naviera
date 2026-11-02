"""add_shipment_charge_adjustments (M-B1)

Phase B (re-pricing on change). Adds the append-only audit table
`shipment_charge_adjustments`: one row per price change of a shipment
(edit, measurement, Payment Dispute, RTO, cancellation, claim and more), with the
old and new bill, the exact delta and links to the wallet transaction and the
GST note that settled it. Also the input for POSTPAID statements.

Spring analogy: a new `@Entity ShipmentChargeAdjustment` with
`@ManyToOne Tenant`, `@ManyToOne ShipmentOrder` and a JSR-303 style CHECK that
`delta = new_total - old_total`.

Additive only: no existing table or row is touched.

Revision ID: 3f9a1c2b7d01
Revises: a8b9c0d1e2f3
Create Date: 2026-10-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "3f9a1c2b7d01"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHARGE_ADJUSTMENT_REASONS = (
    "CUSTOMER_EDIT",
    "ADMIN_EDIT",
    "PICKUP_MEASUREMENT",
    "HUB_MEASUREMENT",
    "MANUAL_WEIGHT_CHARGE",
    "CLAIM_ACCEPTED",
    "PAYMENT_MODE_CHANGE",
    "COD_CHANGE",
    "SHORT_SHIPMENT",
    "FREIGHT_COLLECTION",
    "EXCEPTION_CHARGE",
    "RTO",
    "COD_FEE_REVERSAL",
    "CANCELLATION",
    "PICKUP_REJECTION_REFUND",
    "LOST",
    "LOST_FOUND",
)
"""Mirror of the Python `ChargeAdjustmentReason(str, Enum)` (models/repricing.py, reprice-core)."""

_REASON_LIST_SQL = ", ".join(f"'{reason}'" for reason in CHARGE_ADJUSTMENT_REASONS)


def upgrade() -> None:
    """Creates `shipment_charge_adjustments` with tenant isolation, money CHECKs and indexes."""
    op.execute(
        f"""
        CREATE TABLE shipment_charge_adjustments (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            pickup_id UUID NOT NULL REFERENCES pickups(id) ON DELETE CASCADE,
            reason VARCHAR(32) NOT NULL,
            old_total NUMERIC(12, 2) NOT NULL,
            new_total NUMERIC(12, 2) NOT NULL,
            delta NUMERIC(12, 2) NOT NULL,
            old_chargeable_weight NUMERIC(10, 3) NULL,
            new_chargeable_weight NUMERIC(10, 3) NULL,
            freight_payment_mode freightpaymentmode NOT NULL,
            old_breakdown JSONB NULL,
            new_breakdown JSONB NULL,
            wallet_txn_id UUID NULL REFERENCES wallet_transactions(id) ON DELETE SET NULL,
            billing_invoice_id UUID NULL REFERENCES billing_invoices(id) ON DELETE SET NULL,
            actor_user_id UUID NULL REFERENCES "user"(id) ON DELETE SET NULL,
            idempotency_key VARCHAR(128) NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_charge_adjustments_reason CHECK (reason IN ({_REASON_LIST_SQL})),
            CONSTRAINT ck_charge_adjustments_delta CHECK (delta = new_total - old_total),
            CONSTRAINT ck_charge_adjustments_totals_non_negative CHECK (old_total >= 0 AND new_total >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_charge_adjustments_tenant_id "
        "ON shipment_charge_adjustments (tenant_id)"
    )
    op.execute(
        "CREATE INDEX ix_charge_adjustments_tenant_pickup_created "
        "ON shipment_charge_adjustments (tenant_id, pickup_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_charge_adjustments_wallet_txn_id "
        "ON shipment_charge_adjustments (wallet_txn_id)"
    )
    op.execute(
        "CREATE INDEX ix_charge_adjustments_billing_invoice_id "
        "ON shipment_charge_adjustments (billing_invoice_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_charge_adjustments_tenant_idempotency_key "
        "ON shipment_charge_adjustments (tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    """Drops the table (its indexes and constraints go with it). Audit rows are lost."""
    op.execute("DROP TABLE IF EXISTS shipment_charge_adjustments")
