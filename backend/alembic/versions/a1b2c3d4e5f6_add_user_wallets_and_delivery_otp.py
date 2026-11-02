"""add_user_wallets_and_delivery_otp

Revision ID: a1b2c3d4e5f6
Revises: 944203e6741b
Create Date: 2026-09-22 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "944203e6741b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_wallets (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_wallet_tenant UNIQUE (user_id, tenant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_wallets_tenant_id ON user_wallets (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_wallets_user_id ON user_wallets (user_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id UUID PRIMARY KEY,
            wallet_id UUID NOT NULL REFERENCES user_wallets(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            shipment_id UUID NULL REFERENCES pickups(id) ON DELETE SET NULL,
            tracking_id VARCHAR(100) NULL,
            txn_type VARCHAR(50) NOT NULL,
            service_category VARCHAR(50) NOT NULL,
            opening_balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            closing_balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            utr_number VARCHAR(50) NULL,
            receipt_number VARCHAR(100) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED',
            remarks VARCHAR(500) NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_wallet_txn_utr UNIQUE (utr_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_transactions_wallet_id ON wallet_transactions (wallet_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_transactions_tenant_id ON wallet_transactions (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_transactions_user_id ON wallet_transactions (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_transactions_shipment_id ON wallet_transactions (shipment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_transactions_utr_number ON wallet_transactions (utr_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_transactions_receipt_number ON wallet_transactions (receipt_number)"
    )

    op.execute(
        "ALTER TABLE pickups ADD COLUMN IF NOT EXISTS delivery_otp VARCHAR(6) NULL"
    )
    op.execute(
        "ALTER TABLE pickups ADD COLUMN IF NOT EXISTS pod_received_by VARCHAR(100) NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS pod_received_by")
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS delivery_otp")
    op.execute("DROP TABLE IF EXISTS wallet_transactions")
    op.execute("DROP TABLE IF EXISTS user_wallets")
