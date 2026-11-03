"""public_rls_and_revoke_api_roles (S-1, database backstop for the Supabase Data API)

Naviera never uses the Supabase Data API (PostgREST / GraphQL): FastAPI reads and writes
every table as `postgres`, which owns all `public` tables and has BYPASSRLS. The `anon`
and `authenticated` roles (the Supabase anon key and browser sessions) still held full
table grants and 21 of 25 tables had row-level security off, so the only thing keeping
the tables private was removing `public` from the dashboard's "Exposed schemas".

1. `ENABLE ROW LEVEL SECURITY` (not FORCE) on every `public` table that has it off. No
   policies are added, so non-bypass roles see no rows; `postgres` is unaffected.
2. `REVOKE ALL` on all tables, sequences and functions in `public` from `anon` and
   `authenticated` (`service_role` keeps its grants; it bypasses RLS by design).
3. `ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ... FROM anon,
   authenticated` so tables created by later migrations are not re-exposed. Defaults owned
   by `supabase_admin` cannot be changed by `postgres`; they only cover objects that role
   creates (Naviera's migrations run as `postgres`).

Side effects: catalog-only DDL with brief locks per table, no data rewrite; PgBouncer
pooling unchanged. Downgrade restores the exact pre-upgrade grants (verified on
2026-11-03: `anon`/`authenticated` held `arwdDxtm` on all 25 tables, `Dxtm` table and `w`
sequence defaults, no sequences or functions in `public`) and turns RLS back off on the
21 tables that had it off.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-11-03 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

API_ROLES = "anon, authenticated"
"""Supabase roles behind the anon key and signed-in browser sessions."""
TABLE_CREATOR_ROLE = "postgres"
"""Role that runs the migrations and therefore owns every `public` table."""

TABLES_WITH_RLS_OFF_BEFORE = (
    "addresses",
    "alembic_version",
    "billing_invoices",
    "cod_remittances",
    "idempotency_keys",
    "manifests",
    "package_details",
    "payment_details",
    "pickup_documents",
    "pickups",
    "shipment_activities",
    "shipment_charge_adjustments",
    "shipment_measurements",
    "support_ticket_messages",
    "support_tickets",
    "tenant",
    "tenant_settings_history",
    "user",
    "user_wallets",
    "wallet_transactions",
    "weight_disputes",
)
"""Tables whose RLS was off before this revision; downgrade turns it off on these only."""

ENABLE_RLS_ON_ALL_PUBLIC_TABLES = """
DO $$
DECLARE
    tbl record;
BEGIN
    FOR tbl IN
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl.relname);
    END LOOP;
END $$;
"""

UPGRADE_STATEMENTS: tuple[str, ...] = (
    ENABLE_RLS_ON_ALL_PUBLIC_TABLES,
    f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {API_ROLES}",
    f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {API_ROLES}",
    f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {API_ROLES}",
    f"ALTER DEFAULT PRIVILEGES FOR ROLE {TABLE_CREATOR_ROLE} IN SCHEMA public "
    f"REVOKE ALL ON TABLES FROM {API_ROLES}",
    f"ALTER DEFAULT PRIVILEGES FOR ROLE {TABLE_CREATOR_ROLE} IN SCHEMA public "
    f"REVOKE ALL ON SEQUENCES FROM {API_ROLES}",
    f"ALTER DEFAULT PRIVILEGES FOR ROLE {TABLE_CREATOR_ROLE} IN SCHEMA public "
    f"REVOKE ALL ON FUNCTIONS FROM {API_ROLES}",
)
"""Executed in order by `upgrade()`; also imported by the rolled-back dry run."""

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {API_ROLES}",
    f"ALTER DEFAULT PRIVILEGES FOR ROLE {TABLE_CREATOR_ROLE} IN SCHEMA public "
    f"GRANT TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLES TO {API_ROLES}",
    f"ALTER DEFAULT PRIVILEGES FOR ROLE {TABLE_CREATOR_ROLE} IN SCHEMA public "
    f"GRANT UPDATE ON SEQUENCES TO {API_ROLES}",
    *(
        f'ALTER TABLE IF EXISTS public."{table}" DISABLE ROW LEVEL SECURITY'
        for table in TABLES_WITH_RLS_OFF_BEFORE
    ),
)
"""Restores the pre-upgrade grants, default privileges and RLS flags exactly."""


def upgrade() -> None:
    """Turns RLS on everywhere in `public` and removes the Data API roles' access."""
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Restores the pre-upgrade grants and RLS flags."""
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
