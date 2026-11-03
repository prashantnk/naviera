"""storage_documents_tenant_policies (S-2, tenant isolation for the `documents` bucket)

Before this revision any signed-in Supabase session could read (sign) or upload any
object in the private `documents` bucket: the dashboard policies only checked
`bucket_id = 'documents'`. Every upload path in the frontend already starts with the
tenant slug (`<tenant_slug>/<file>`), and the 6 live objects all sit under `logismart/`.

The JWTs Storage sees (GoTrue sessions and the backend-minted password sessions, both
HS256 with the project JWT secret) carry `sub` = `auth.users.id` but no tenant claim, and
one auth account can belong to several tenants. The policies therefore look the caller up:

1. Schema `naviera_private` (not exposed through the Data API) with
   `is_active_tenant_member(tenant_slug)`: SECURITY DEFINER, `search_path = ''`, true when
   an active `public."user"` row of that tenant has `supabase_user_id = auth.uid()`.
   Only `authenticated` may execute it; it reveals nothing beyond a boolean about the
   caller's own memberships.
2. The two permissive dashboard policies are replaced by
   `documents_tenant_member_select` (SELECT, which also governs signed URLs) and
   `documents_tenant_member_insert` (INSERT), both requiring the first path segment to be
   a tenant the caller belongs to. No UPDATE/DELETE policy: uploads never overwrite and
   nothing deletes from the browser, so stored evidence is immutable for clients.

Side effects: none on data; `anon` keeps no access. Downgrade recreates the two original
dashboard policies verbatim and drops the helper schema.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-11-03 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUCKET = "documents"
HELPER_SCHEMA = "naviera_private"
HELPER_FUNCTION = f"{HELPER_SCHEMA}.is_active_tenant_member(text)"
LEGACY_INSERT_POLICY = '"Allow Authenticated Uploads flreew_0"'
LEGACY_SELECT_POLICY = '"Allow Authenticated to View Documents flreew_0"'
SELECT_POLICY = "documents_tenant_member_select"
INSERT_POLICY = "documents_tenant_member_insert"

TENANT_PATH_CHECK = (
    f"bucket_id = '{BUCKET}' AND "
    f"{HELPER_SCHEMA}.is_active_tenant_member((storage.foldername(name))[1])"
)
"""First object-path segment must be a tenant slug the caller is an active member of."""

CREATE_HELPER_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {HELPER_SCHEMA}.is_active_tenant_member(tenant_slug text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public."user" AS u
        JOIN public.tenant AS t ON t.id = u.tenant_id
        WHERE t.slug = tenant_slug
          AND u.is_active
          AND u.supabase_user_id = (SELECT auth.uid())::text
    )
$$
"""

UPGRADE_STATEMENTS: tuple[str, ...] = (
    f"CREATE SCHEMA IF NOT EXISTS {HELPER_SCHEMA}",
    f"REVOKE ALL ON SCHEMA {HELPER_SCHEMA} FROM PUBLIC",
    f"GRANT USAGE ON SCHEMA {HELPER_SCHEMA} TO authenticated",
    CREATE_HELPER_FUNCTION,
    f"REVOKE ALL ON FUNCTION {HELPER_FUNCTION} FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION {HELPER_FUNCTION} TO authenticated",
    f"DROP POLICY IF EXISTS {LEGACY_INSERT_POLICY} ON storage.objects",
    f"DROP POLICY IF EXISTS {LEGACY_SELECT_POLICY} ON storage.objects",
    f"CREATE POLICY {SELECT_POLICY} ON storage.objects FOR SELECT TO authenticated "
    f"USING ({TENANT_PATH_CHECK})",
    f"CREATE POLICY {INSERT_POLICY} ON storage.objects FOR INSERT TO authenticated "
    f"WITH CHECK ({TENANT_PATH_CHECK})",
)
"""Executed in order by `upgrade()`; also imported by the rolled-back dry run."""

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    f"DROP POLICY IF EXISTS {INSERT_POLICY} ON storage.objects",
    f"DROP POLICY IF EXISTS {SELECT_POLICY} ON storage.objects",
    f"CREATE POLICY {LEGACY_INSERT_POLICY} ON storage.objects FOR INSERT TO authenticated "
    f"WITH CHECK (bucket_id = '{BUCKET}')",
    f"CREATE POLICY {LEGACY_SELECT_POLICY} ON storage.objects FOR SELECT TO authenticated "
    f"USING (bucket_id = '{BUCKET}')",
    f"DROP FUNCTION IF EXISTS {HELPER_FUNCTION}",
    f"DROP SCHEMA IF EXISTS {HELPER_SCHEMA}",
)
"""Restores the two original dashboard policies verbatim."""


def upgrade() -> None:
    """Scopes `documents` reads and uploads to the caller's tenant folder."""
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Restores the bucket-wide authenticated policies."""
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
