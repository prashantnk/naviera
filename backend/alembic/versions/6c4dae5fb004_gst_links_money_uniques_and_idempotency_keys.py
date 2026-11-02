"""gst_links_money_uniques_and_idempotency_keys (M-B4)

Phase B. Database-level "only once" guarantees and GST document links:

1. `billing_invoices` gets three columns (no data backfill, user choice (b)
   on 2026-10-27; existing rows keep NULL links and bill_to_type MERCHANT):
   - `shipment_id` (FK pickups, ON DELETE SET NULL): today the link lives only
     inside the `line_items` JSON.
   - `original_invoice_id` (FK billing_invoices): the INVOICE that a
     CREDIT_NOTE / DEBIT_NOTE corrects (CGST Rule 53). An INVOICE never carries one.
   - `bill_to_type VARCHAR(16) NOT NULL DEFAULT 'MERCHANT'` + CHECK
     (MERCHANT, CONSIGNEE).
2. Unique `(tenant_id, invoice_number)`: a GST number can never repeat.
3. Partial unique `(tenant_id, shipment_id, bill_to_type) WHERE note_type = 'INVOICE'`:
   at most one INVOICE per shipment per bill-to party.
4. Partial unique `wallet_transactions (shipment_id, txn_type)` for
   `COD_SETTLEMENT` and `RTO_FREIGHT`: no double COD payout, no double RTO bill (H-2).
5. New table `idempotency_keys` for the `Idempotency-Key` header on money POSTs (H-4).

`wallet_transactions.txn_type` is a plain VARCHAR(50) with **no** CHECK constraint
(verified read-only against the live database on 2026-10-27), so the new txn
types `RTO_FREIGHT` and `CHARGE_REVERSAL` need no schema change.

Revision ID: 6c4dae5fb004
Revises: 5b3c9d4eaf03
Create Date: 2026-10-27 15:00:03.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "6c4dae5fb004"
down_revision: Union[str, Sequence[str], None] = "5b3c9d4eaf03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BILL_TO_TYPES = ("MERCHANT", "CONSIGNEE")
"""Mirror of the Python `BillToType(str, Enum)` (models/delhivery_modules.py, contracts)."""

ONE_PER_SHIPMENT_TXN_TYPES = ("COD_SETTLEMENT", "RTO_FREIGHT")
"""Wallet txn types that may exist at most once per shipment (WalletTxnType values)."""

_BILL_TO_LIST_SQL = ", ".join(f"'{value}'" for value in BILL_TO_TYPES)
_TXN_LIST_SQL = ", ".join(f"'{value}'" for value in ONE_PER_SHIPMENT_TXN_TYPES)


def _add_billing_invoice_columns() -> None:
    """Adds shipment_id, original_invoice_id and bill_to_type with their FKs and CHECKs."""
    op.execute(
        "ALTER TABLE billing_invoices ADD COLUMN shipment_id UUID NULL "
        "REFERENCES pickups(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE billing_invoices ADD COLUMN original_invoice_id UUID NULL "
        "REFERENCES billing_invoices(id)"
    )
    op.execute(
        "ALTER TABLE billing_invoices "
        "ADD COLUMN bill_to_type VARCHAR(16) NOT NULL DEFAULT 'MERCHANT'"
    )
    op.execute(
        "ALTER TABLE billing_invoices ADD CONSTRAINT ck_billing_invoices_bill_to_type "
        f"CHECK (bill_to_type IN ({_BILL_TO_LIST_SQL}))"
    )
    op.execute(
        "ALTER TABLE billing_invoices ADD CONSTRAINT ck_billing_invoices_original_only_on_notes "
        "CHECK (original_invoice_id IS NULL OR note_type <> 'INVOICE')"
    )


def _create_unique_indexes() -> None:
    """Indexes for the new FKs plus the three 'only once' unique indexes."""
    op.execute("CREATE INDEX ix_billing_invoices_shipment_id ON billing_invoices (shipment_id)")
    op.execute(
        "CREATE INDEX ix_billing_invoices_original_invoice_id "
        "ON billing_invoices (original_invoice_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_billing_invoices_tenant_invoice_number "
        "ON billing_invoices (tenant_id, invoice_number)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_billing_invoices_one_invoice_per_shipment "
        "ON billing_invoices (tenant_id, shipment_id, bill_to_type) "
        "WHERE note_type = 'INVOICE' AND shipment_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_wallet_txn_once_per_shipment "
        "ON wallet_transactions (shipment_id, txn_type) "
        f"WHERE txn_type IN ({_TXN_LIST_SQL}) AND shipment_id IS NOT NULL"
    )


def _create_idempotency_keys() -> None:
    """Creates `idempotency_keys`, scoped per tenant + user + endpoint + key."""
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            endpoint VARCHAR(128) NOT NULL,
            key VARCHAR(128) NOT NULL,
            request_hash VARCHAR(64) NOT NULL,
            response JSONB NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_idempotency_keys_scope UNIQUE (tenant_id, user_id, endpoint, key)
        )
        """
    )
    op.execute("CREATE INDEX ix_idempotency_keys_tenant_id ON idempotency_keys (tenant_id)")
    op.execute("CREATE INDEX ix_idempotency_keys_created_at ON idempotency_keys (created_at)")


def upgrade() -> None:
    """Applies the three steps in one transaction (all-or-nothing). No data backfill (user choice b)."""
    _add_billing_invoice_columns()
    _create_unique_indexes()
    _create_idempotency_keys()


def downgrade() -> None:
    """Drops the new table, indexes, constraints and columns. The JSON link in line_items stays."""
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
    op.execute("DROP INDEX IF EXISTS uq_wallet_txn_once_per_shipment")
    op.execute("DROP INDEX IF EXISTS uq_billing_invoices_one_invoice_per_shipment")
    op.execute("DROP INDEX IF EXISTS uq_billing_invoices_tenant_invoice_number")
    op.execute("DROP INDEX IF EXISTS ix_billing_invoices_original_invoice_id")
    op.execute("DROP INDEX IF EXISTS ix_billing_invoices_shipment_id")
    op.execute(
        "ALTER TABLE billing_invoices DROP CONSTRAINT IF EXISTS ck_billing_invoices_original_only_on_notes"
    )
    op.execute("ALTER TABLE billing_invoices DROP CONSTRAINT IF EXISTS ck_billing_invoices_bill_to_type")
    op.execute("ALTER TABLE billing_invoices DROP COLUMN IF EXISTS bill_to_type")
    op.execute("ALTER TABLE billing_invoices DROP COLUMN IF EXISTS original_invoice_id")
    op.execute("ALTER TABLE billing_invoices DROP COLUMN IF EXISTS shipment_id")
