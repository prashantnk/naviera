"""delhivery_one_parity_modules

Additive migration (M1) for Delhivery One parity modules:
1. Extend `user` table with `full_name`, `phone`, `delhivery_role`, and `created_at`
2. `support_tickets` and `support_ticket_messages`
3. `cod_remittances`
4. `billing_invoices`
5. `weight_disputes`

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-16 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend "user" table
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS full_name VARCHAR(120) NULL'
    )
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS phone VARCHAR(24) NULL'
    )
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS delhivery_role VARCHAR(32) NOT NULL DEFAULT \'OWNER\''
    )
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NULL DEFAULT now()'
    )

    # 2. support_tickets
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS support_tickets (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
            ticket_number VARCHAR(64) NOT NULL,
            shipment_id UUID NULL REFERENCES pickups (id) ON DELETE SET NULL,
            tracking_id VARCHAR(100) NULL,
            category_group VARCHAR(64) NOT NULL DEFAULT 'SHIPMENT_ISSUE',
            sub_category VARCHAR(255) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
            cc_emails JSONB NOT NULL DEFAULT '[]'::jsonb,
            email_notifications BOOLEAN NOT NULL DEFAULT TRUE,
            raised_by_email VARCHAR(255) NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_tickets_tenant_id ON support_tickets (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id ON support_tickets (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_tickets_ticket_number ON support_tickets (ticket_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_tickets_tracking_id ON support_tickets (tracking_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_tickets_status ON support_tickets (status)"
    )

    # 3. support_ticket_messages
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS support_ticket_messages (
            id UUID PRIMARY KEY,
            ticket_id UUID NOT NULL REFERENCES support_tickets (id) ON DELETE CASCADE,
            sender_user_id UUID NOT NULL,
            sender_email VARCHAR(255) NOT NULL,
            sender_role VARCHAR(64) NOT NULL,
            message TEXT NOT NULL,
            attachment_url VARCHAR(512) NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_ticket_messages_ticket_id ON support_ticket_messages (ticket_id)"
    )

    # 4. cod_remittances
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cod_remittances (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            merchant_user_id UUID NOT NULL,
            remittance_number VARCHAR(64) NOT NULL,
            processed_date DATE NOT NULL,
            bank_utr VARCHAR(64) NOT NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'Completed',
            total_remittance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            total_orders INTEGER NOT NULL DEFAULT 0,
            shipment_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cod_remittances_tenant_id ON cod_remittances (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cod_remittances_merchant_user_id ON cod_remittances (merchant_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cod_remittances_remittance_number ON cod_remittances (remittance_number)"
    )

    # 5. billing_invoices
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_invoices (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            merchant_user_id UUID NOT NULL,
            invoice_number VARCHAR(64) NOT NULL,
            note_type VARCHAR(32) NOT NULL DEFAULT 'INVOICE',
            service_type VARCHAR(64) NOT NULL DEFAULT 'Domestic',
            invoice_date DATE NOT NULL,
            due_date DATE NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'Paid',
            gst_number VARCHAR(32) NOT NULL DEFAULT '06AAECL2138H1ZQ',
            billing_address TEXT NOT NULL DEFAULT 'H. NO-632/5, GALI NO-3, PATEL NAGAR, JYOTI HOSPITAL, Gurgaon, Haryana, 122001',
            freight_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            cgst_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            sgst_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            igst_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            total_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            line_items JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_invoices_tenant_id ON billing_invoices (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_invoices_merchant_user_id ON billing_invoices (merchant_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_invoices_invoice_number ON billing_invoices (invoice_number)"
    )

    # 6. weight_disputes
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS weight_disputes (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            merchant_user_id UUID NOT NULL,
            shipment_id UUID NULL REFERENCES pickups (id) ON DELETE SET NULL,
            tracking_id VARCHAR(100) NOT NULL,
            order_reference_id VARCHAR(100) NULL,
            shipment_status VARCHAR(64) NOT NULL DEFAULT 'Delivered',
            manifested_weight_g DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            charged_weight_g DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            claimed_weight_g DOUBLE PRECISION NULL,
            manifested_dims VARCHAR(120) NOT NULL DEFAULT '39 x 30 x 6 cm',
            charged_dims VARCHAR(120) NOT NULL DEFAULT '23.8 x 31.8 x 7.3 cm',
            shipping_cost_inr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            shipment_value_inr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            cost_diff_inr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            sorter_image_url VARCHAR(512) NULL,
            claim_status VARCHAR(32) NOT NULL DEFAULT 'NONE',
            claim_remarks TEXT NULL,
            raised_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_weight_disputes_tenant_id ON weight_disputes (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_weight_disputes_merchant_user_id ON weight_disputes (merchant_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_weight_disputes_tracking_id ON weight_disputes (tracking_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weight_disputes")
    op.execute("DROP TABLE IF EXISTS billing_invoices")
    op.execute("DROP TABLE IF EXISTS cod_remittances")
    op.execute("DROP TABLE IF EXISTS support_ticket_messages")
    op.execute("DROP TABLE IF EXISTS support_tickets")
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS delhivery_role')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS phone')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS full_name')
