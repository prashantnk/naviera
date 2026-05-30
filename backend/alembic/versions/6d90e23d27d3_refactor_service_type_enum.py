"""refactor_service_type_enum

Revision ID: 6d90e23d27d3
Revises: c730485a140f
Create Date: 2026-05-30 13:36:16.139868

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = '6d90e23d27d3'
down_revision: Union[str, Sequence[str], None] = 'c730485a140f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # PostgreSQL enum mutation strategy:
    # 1. Rename old enum
    op.execute("ALTER TYPE servicetype RENAME TO servicetype_old")
    # 2. Create new enum
    op.execute("CREATE TYPE servicetype AS ENUM ('SURFACE_ROAD', 'SURFACE_TRAIN', 'AIR')")
    # 3. Drop column default value
    op.execute("ALTER TABLE pickups ALTER COLUMN service_type DROP DEFAULT")
    # 4. Alter column type and map values
    op.execute(
        "ALTER TABLE pickups ALTER COLUMN service_type TYPE servicetype USING "
        "(CASE service_type::text "
        "WHEN 'SURFACE' THEN 'SURFACE_ROAD'::servicetype "
        "WHEN 'EXPRESS' THEN 'AIR'::servicetype "
        "ELSE 'SURFACE_ROAD'::servicetype END)"
    )
    # 5. Set new column default
    op.execute("ALTER TABLE pickups ALTER COLUMN service_type SET DEFAULT 'SURFACE_ROAD'::servicetype")
    # 6. Drop old enum type
    op.execute("DROP TYPE servicetype_old")


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Rename new enum
    op.execute("ALTER TYPE servicetype RENAME TO servicetype_new")
    # 2. Create old enum
    op.execute("CREATE TYPE servicetype AS ENUM ('SURFACE', 'EXPRESS')")
    # 3. Drop column default value
    op.execute("ALTER TABLE pickups ALTER COLUMN service_type DROP DEFAULT")
    # 4. Alter column type and map values back
    op.execute(
        "ALTER TABLE pickups ALTER COLUMN service_type TYPE servicetype USING "
        "(CASE service_type::text "
        "WHEN 'SURFACE_ROAD' THEN 'SURFACE'::servicetype "
        "WHEN 'SURFACE_TRAIN' THEN 'SURFACE'::servicetype "
        "WHEN 'AIR' THEN 'EXPRESS'::servicetype "
        "ELSE 'SURFACE'::servicetype END)"
    )
    # 5. Set old column default
    op.execute("ALTER TABLE pickups ALTER COLUMN service_type SET DEFAULT 'SURFACE'::servicetype")
    # 6. Drop temporary enum type
    op.execute("DROP TYPE servicetype_new")

