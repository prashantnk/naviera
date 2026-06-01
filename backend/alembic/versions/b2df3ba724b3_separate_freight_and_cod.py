"""separate_freight_and_cod

Revision ID: b2df3ba724b3
Revises: d5f000c3f65a
Create Date: 2026-05-31 19:05:09.580852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2df3ba724b3'
down_revision: Union[str, Sequence[str], None] = 'd5f000c3f65a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create the custom PostgreSQL enum types manually before column mapping
    op.execute("CREATE TYPE freightpaymentmode AS ENUM ('PREPAID', 'POSTPAID', 'TO_PAY')")
    op.execute("CREATE TYPE codremittancestatus AS ENUM ('NOT_APPLICABLE', 'PENDING_COLLECTION', 'COLLECTED', 'REMITTED', 'FAILED_RTO')")

    # 2. Add the new columns as NULLABLE initially to allow data mapping for existing records
    op.add_column('payment_details', sa.Column('freight_payment_mode', sa.Enum('PREPAID', 'POSTPAID', 'TO_PAY', name='freightpaymentmode'), nullable=True))
    op.add_column('payment_details', sa.Column('is_cod', sa.Boolean(), nullable=True))
    op.add_column('payment_details', sa.Column('cod_amount', sa.Float(), nullable=True))
    op.add_column('payment_details', sa.Column('cod_remittance_status', sa.Enum('NOT_APPLICABLE', 'PENDING_COLLECTION', 'COLLECTED', 'REMITTED', 'FAILED_RTO', name='codremittancestatus'), nullable=True))
    op.add_column('payment_details', sa.Column('base_freight', sa.Float(), nullable=True))
    op.add_column('payment_details', sa.Column('total_logistics_cost', sa.Float(), nullable=True))
    op.add_column('payment_details', sa.Column('pricing_breakdown', sa.JSON(), nullable=True))

    # 3. Run Data Migration to preserve historical record payments
    # Map PREPAID or NULL to new PREPAID structure
    op.execute("""
        UPDATE payment_details SET 
            freight_payment_mode = 'PREPAID',
            is_cod = FALSE,
            cod_amount = 0.0,
            cod_remittance_status = 'NOT_APPLICABLE',
            base_freight = amount,
            total_logistics_cost = amount,
            pricing_breakdown = '{}'::jsonb
        WHERE payment_mode = 'PREPAID' OR payment_mode IS NULL
    """)
    
    # Map COD to new structured cash-collection variables
    op.execute("""
        UPDATE payment_details SET 
            freight_payment_mode = 'PREPAID',
            is_cod = TRUE,
            cod_amount = amount,
            cod_remittance_status = 'PENDING_COLLECTION',
            base_freight = amount,
            total_logistics_cost = amount,
            pricing_breakdown = '{}'::jsonb
        WHERE payment_mode = 'COD'
    """)

    # 4. Enforce NOT NULL constraints now that all historical data has been successfully mapped
    op.alter_column('payment_details', 'freight_payment_mode', nullable=False)
    op.alter_column('payment_details', 'is_cod', nullable=False)
    op.alter_column('payment_details', 'cod_amount', nullable=False)
    op.alter_column('payment_details', 'cod_remittance_status', nullable=False)
    op.alter_column('payment_details', 'base_freight', nullable=False)
    op.alter_column('payment_details', 'total_logistics_cost', nullable=False)

    # 5. Drop the obsolete payment_mode column and its associated PG type
    op.drop_column('payment_details', 'payment_mode')
    op.execute("DROP TYPE IF EXISTS paymentmode")


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Re-create the obsolete type and column
    op.execute("CREATE TYPE paymentmode AS ENUM ('PREPAID', 'COD')")
    op.add_column('payment_details', sa.Column('payment_mode', sa.Enum('PREPAID', 'COD', name='paymentmode'), nullable=True))

    # 2. Map data back: if it was COD, restore 'COD', otherwise 'PREPAID'
    op.execute("""
        UPDATE payment_details SET 
            payment_mode = CASE WHEN is_cod = TRUE THEN 'COD'::paymentmode ELSE 'PREPAID'::paymentmode END
    """)
    
    # Make column NOT NULL
    op.alter_column('payment_details', 'payment_mode', nullable=False)

    # 3. Drop all newly added columns
    op.drop_column('payment_details', 'pricing_breakdown')
    op.drop_column('payment_details', 'total_logistics_cost')
    op.drop_column('payment_details', 'base_freight')
    op.drop_column('payment_details', 'cod_remittance_status')
    op.drop_column('payment_details', 'cod_amount')
    op.drop_column('payment_details', 'is_cod')
    op.drop_column('payment_details', 'freight_payment_mode')

    # 4. Drop the custom types
    op.execute("DROP TYPE freightpaymentmode")
    op.execute("DROP TYPE codremittancestatus")

