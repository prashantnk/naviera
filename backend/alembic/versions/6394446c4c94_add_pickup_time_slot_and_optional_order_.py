"""add pickup time slot and optional order id

Revision ID: 6394446c4c94
Revises: 6d90e23d27d3
Create Date: 2026-05-30 17:51:12.403085

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6394446c4c94'
down_revision: Union[str, Sequence[str], None] = '6d90e23d27d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create custom PG Enum type
    sa.Enum('MORNING_06_10', 'MIDDAY_10_14', 'AFTERNOON_14_18', 'EVENING_18_22', name='pickuptimeslot').create(op.get_bind())
    # 2. Add column utilizing the custom Enum
    op.add_column('pickups', sa.Column('pickup_time_slot', sa.Enum('MORNING_06_10', 'MIDDAY_10_14', 'AFTERNOON_14_18', 'EVENING_18_22', name='pickuptimeslot'), nullable=True))
    op.alter_column('pickups', 'order_reference_id',
               existing_type=sa.VARCHAR(length=100),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('pickups', 'order_reference_id',
               existing_type=sa.VARCHAR(length=100),
               nullable=False)
    # 1. Drop column first
    op.drop_column('pickups', 'pickup_time_slot')
    # 2. Drop custom PG Enum type
    sa.Enum(name='pickuptimeslot').drop(op.get_bind())
