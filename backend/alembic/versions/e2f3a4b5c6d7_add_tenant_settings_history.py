"""add_tenant_settings_history

Platform Settings version history (Phase O.7, S1).

Strictly additive and idempotent (single shared Supabase instance):
  tenant_settings_history (
      id UUID PK,
      tenant_id UUID NOT NULL -> tenant.id ON DELETE CASCADE (indexed),
      version INT NOT NULL,
      settings JSONB NOT NULL,
      changed_by_user_id UUID NULL -> user.id ON DELETE SET NULL,
      changed_sections TEXT[] NOT NULL DEFAULT '{}',
      created_at TIMESTAMP NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, version)
  )
The application keeps only the last 20 versions per tenant (pruned on insert).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-16 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tenant_settings_history (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    settings JSONB NOT NULL,
    changed_by_user_id UUID NULL REFERENCES "user" (id) ON DELETE SET NULL,
    changed_sections TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_settings_history_version UNIQUE (tenant_id, version)
)
"""


def upgrade() -> None:
    op.execute(CREATE_TABLE_SQL)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tenant_settings_history_tenant_id "
        "ON tenant_settings_history (tenant_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenant_settings_history_tenant_id")
    op.execute("DROP TABLE IF EXISTS tenant_settings_history")
