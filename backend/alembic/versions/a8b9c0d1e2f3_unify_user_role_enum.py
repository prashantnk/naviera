"""unify_user_role_enum

Unifies all 6 workspace roles into the single `userrole` PostgreSQL enum
('owner', 'admin', 'operations_user', 'support_user', 'read_only_user', 'customer')
and drops the redundant `delhivery_role` column from `public."user"`.

Revision ID: a8b9c0d1e2f3
Revises: f3a4b5c6d7e8
Create Date: 2026-10-17 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'operations_user'")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'support_user'")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'read_only_user'")

    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS delhivery_role')


def downgrade() -> None:
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS delhivery_role VARCHAR(32) NOT NULL DEFAULT \'OWNER\''
    )
