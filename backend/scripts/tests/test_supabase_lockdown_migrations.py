"""
Pure checks for the Supabase Data API / Storage lockdown migrations (no database access).

Run from `naviera/backend`:
    poetry run python -m pytest --noconftest scripts/tests/test_supabase_lockdown_migrations.py -q

`d7e8f9a0b1c2` turns RLS on for every `public` table and revokes the `anon` /
`authenticated` grants; `e8f9a0b1c2d3` scopes the private `documents` bucket to the
caller's tenant folder. The rolled-back dry run on the shared database and the post-upgrade
catalog checks live in `llm_resources/.agents/rel3/secdb/` (see docs/RUNBOOK.md §3).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table on SQLModel.metadata)

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
TABLES_WITH_RLS_ALREADY_ON = {"delhivery_price_cache", "prime_lanes", "prime_zone_pincodes", "prime_zones"}
"""Created by M-P1/M-P2 with RLS enabled; the downgrade must leave them alone."""


def _load_revision(revision: str) -> ModuleType:
    (path,) = VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"rev_{revision}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rls() -> ModuleType:
    return _load_revision("d7e8f9a0b1c2")


@pytest.fixture(scope="module")
def storage() -> ModuleType:
    return _load_revision("e8f9a0b1c2d3")


def test_revision_chain(rls: ModuleType, storage: ModuleType) -> None:
    assert rls.down_revision == "c6d7e8f9a0b1"
    assert storage.down_revision == rls.revision == "d7e8f9a0b1c2"


def test_rls_is_enabled_without_force(rls: ModuleType) -> None:
    upgrade_sql = "\n".join(rls.UPGRADE_STATEMENTS)
    assert "ENABLE ROW LEVEL SECURITY" in upgrade_sql
    assert "NOT c.relrowsecurity" in upgrade_sql
    assert "FORCE" not in upgrade_sql.upper()


@pytest.mark.parametrize("object_kind", ["TABLES", "SEQUENCES", "FUNCTIONS"])
def test_api_roles_lose_current_and_default_privileges(rls: ModuleType, object_kind: str) -> None:
    statements = rls.UPGRADE_STATEMENTS
    assert f"REVOKE ALL ON ALL {object_kind} IN SCHEMA public FROM anon, authenticated" in statements
    assert (
        f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        f"REVOKE ALL ON {object_kind} FROM anon, authenticated"
    ) in statements
    assert not any("service_role" in statement for statement in statements)


def test_downgrade_list_matches_the_model_tables_that_had_rls_off(rls: ModuleType) -> None:
    model_tables = set(SQLModel.metadata.tables)
    expected = (model_tables - TABLES_WITH_RLS_ALREADY_ON) | {"alembic_version"}
    assert set(rls.TABLES_WITH_RLS_OFF_BEFORE) == expected
    disabled = [s for s in rls.DOWNGRADE_STATEMENTS if "DISABLE ROW LEVEL SECURITY" in s]
    assert len(disabled) == len(rls.TABLES_WITH_RLS_OFF_BEFORE) == 21
    assert not any(table in " ".join(disabled) for table in TABLES_WITH_RLS_ALREADY_ON)


def test_storage_policies_scope_documents_to_the_tenant_folder(storage: ModuleType) -> None:
    created = [s for s in storage.UPGRADE_STATEMENTS if s.startswith("CREATE POLICY")]
    assert [s.split(" FOR ")[1].split()[0] for s in created] == ["SELECT", "INSERT"]
    for statement in created:
        assert "TO authenticated" in statement
        assert "bucket_id = 'documents'" in statement
        assert "naviera_private.is_active_tenant_member((storage.foldername(name))[1])" in statement
    dropped = [s for s in storage.UPGRADE_STATEMENTS if s.startswith("DROP POLICY")]
    assert len(dropped) == 2


def test_membership_helper_is_locked_down(storage: ModuleType) -> None:
    function_sql = storage.CREATE_HELPER_FUNCTION
    assert "SECURITY DEFINER" in function_sql
    assert "SET search_path = ''" in function_sql
    assert "u.is_active" in function_sql
    assert "(SELECT auth.uid())::text" in function_sql
    assert f"REVOKE ALL ON FUNCTION {storage.HELPER_FUNCTION} FROM PUBLIC" in storage.UPGRADE_STATEMENTS
    assert f"GRANT EXECUTE ON FUNCTION {storage.HELPER_FUNCTION} TO authenticated" in storage.UPGRADE_STATEMENTS


def test_storage_downgrade_restores_the_dashboard_policies(storage: ModuleType) -> None:
    downgrade_sql = "\n".join(storage.DOWNGRADE_STATEMENTS)
    assert '"Allow Authenticated Uploads flreew_0" ON storage.objects FOR INSERT' in downgrade_sql
    assert '"Allow Authenticated to View Documents flreew_0" ON storage.objects FOR SELECT' in downgrade_sql
    assert downgrade_sql.rstrip().endswith("DROP SCHEMA IF EXISTS naviera_private")
