"""add_package_dimension_and_weight_units

Revision ID: 4bf316b4ecbb
Revises: 7faf47557960
Create Date: 2026-06-02 14:25:50.489150

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bf316b4ecbb'
down_revision: Union[str, Sequence[str], None] = '7faf47557960'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create ENUM types
    dimensionunit_enum = sa.Enum('CM', 'M', 'IN', 'FT', name='dimensionunit')
    weightunit_enum = sa.Enum('KG', 'G', name='weightunit')
    dimensionunit_enum.create(op.get_bind(), checkfirst=True)
    weightunit_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add columns with nullable=True initially so we can backfill safely
    op.add_column('package_details', sa.Column('dimension_unit', sa.Enum('CM', 'M', 'IN', 'FT', name='dimensionunit'), nullable=True))
    op.add_column('package_details', sa.Column('weight_unit', sa.Enum('KG', 'G', name='weightunit'), nullable=True))

    # 3. Backfill existing packages with CM and KG
    op.execute("UPDATE package_details SET dimension_unit = 'CM'::dimensionunit, weight_unit = 'KG'::weightunit")

    # 4. Set nullable=False on new columns
    op.alter_column('package_details', 'dimension_unit', nullable=False)
    op.alter_column('package_details', 'weight_unit', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop columns
    op.drop_column('package_details', 'weight_unit')
    op.drop_column('package_details', 'dimension_unit')

    # 2. Drop Enum types
    sa.Enum(name='dimensionunit').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='weightunit').drop(op.get_bind(), checkfirst=True)

