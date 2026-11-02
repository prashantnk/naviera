"""add_service_scope_to_users

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-10-02 22:55:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS service_scope VARCHAR(16) NOT NULL DEFAULT \'B2C\''
    )
    op.execute(
        "UPDATE \"user\" SET service_scope = 'BOTH' WHERE role IN ('admin', 'owner')"
    )


def downgrade() -> None:
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS service_scope')
