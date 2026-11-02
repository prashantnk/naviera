"""
Static tenant-isolation guard for the repository layer (ship-readiness plan §2.0, item E2).

AGENTS.md §5 says every repository query must filter by `tenant_id`. This test
parses every module in `backend/app/repositories/` with the `ast` module (no
import, no database) and fails when a repository method that runs or builds a
query cannot prove that it is tenant-scoped.

A method passes when ONE of these holds:

1. TENANT PARAM: it takes a `tenant_id` parameter AND reads `tenant_id` in its body
   (a parameter that is accepted but ignored is itself a failure).
2. SCOPE PARAM: it takes a `scope` parameter whose NamedTuple type (defined in the
   same module) has a `tenant_id` field, and it passes `scope` on. A second test
   checks that every `_scope_filters(scope)` helper really compares `scope.tenant_id`.
3. ENTITY SCOPED: it reads `<param>.tenant_id` or `<param>.id` of an entity it was given
   (for example `manifest.tenant_id`, or re-loading `pickup.id` right after writing it),
   so the tenant is inherited from a row the service built or loaded through a
   tenant-filtered query.
4. NO QUERY: its body builds or runs no query at all (no `select/update/delete/insert/text`
   call, no `session.get/exec/execute/scalar(s)`). Such methods only persist an entity
   whose `tenant_id` the service already set (`session.add`, `commit`, `refresh`).
5. ALLOW-LISTED: it is in `ALLOW_LIST` below, each entry with a written reason.

New repository files and methods (for example the Phase B `repositories/repricing.py`)
are picked up automatically, so a new unscoped query fails CI until it is fixed or
justified here.

Spring analogy: an ArchUnit rule ("every `JpaRepository` query method must take a
tenant key"), enforced at build time instead of in code review.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterator, List, Optional, Set, Union

import pytest

# --- Constants -------------------------------------------------------------

REPOSITORIES_DIR = Path(__file__).resolve().parents[2] / "app" / "repositories"
TENANT_PARAM = "tenant_id"
SCOPE_PARAM = "scope"
TENANT_FIELD = "tenant_id"
ENTITY_SCOPE_ATTRS: FrozenSet[str] = frozenset({"tenant_id", "id"})
SCOPE_FILTER_HELPER = "_scope_filters"
SELF_PARAMS: FrozenSet[str] = frozenset({"self", "cls"})
QUERY_BUILDER_CALLS: FrozenSet[str] = frozenset({"select", "update", "delete", "insert", "text"})
SESSION_QUERY_METHODS: FrozenSet[str] = frozenset({"get", "exec", "execute", "scalar", "scalars"})
SESSION_NAMES: FrozenSet[str] = frozenset({"session", "_session", "db"})

FuncNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

# --- Allow-list ------------------------------------------------------------
# Key: "<module>.<Class>.<method>". Every entry MUST say why it is safe.
# A stale key (method renamed or deleted) fails `test_allow_list_has_no_stale_entries`.

ALLOW_LIST: Dict[str, str] = {
    # ---- Genuinely global lookups -------------------------------------------
    "tenants.TenantRepository.list_tenants": (
        "Platform super-admin view of all tenants; the endpoint is the only cross-tenant "
        "screen by design and is guarded in the service layer."
    ),
    "tenants.TenantRepository.get_tenant_by_slug": (
        "Resolves the tenant itself from the X-Tenant-Slug header; there is no tenant yet to filter by."
    ),
    "tenants.TenantRepository.get_auth_user_by_email": (
        "Supabase `auth.users` is one global identity table shared by all tenants; tenant "
        "membership is checked afterwards against `users` (unique_user_tenant)."
    ),
    "tenants.TenantRepository.verify_auth_user_password": (
        "Global Supabase `auth.users` password check (identity, not tenant data)."
    ),
    "tenants.TenantRepository.create_auth_user_with_password": (
        "Creates the global Supabase identity; the tenant-scoped `users` row is created separately."
    ),
    "wallet.WalletRepository.get_transaction_by_utr": (
        "An NPCI UTR is globally unique (DB constraint uq_wallet_txn_utr), so the duplicate-UTR "
        "anti-replay check must look across every tenant. Only existence is used (409), no data "
        "from another tenant is returned to the caller (services/wallet.py:443-447, :636-640)."
    ),
    "shipments.ShipmentRepository.check_tracking_id_exists": (
        "Collision check while generating a new AWB/LR; AWBs must be unique across tenants "
        "because public tracking resolves them. Returns a bool only (services/shipment.py:368)."
    ),
    # ---- By-id lookups whose caller verifies the tenant ---------------------
    "addresses.AddressRepository.get_address_by_id": (
        "Every caller checks `address.tenant_id != tenant.id` and returns 404 "
        "(services/addresses.py:125-127, :192-194). Known debt: move the filter into the query."
    ),
    "tenants.TenantRepository.get_user_by_id": (
        "Callers check `target_user.tenant_id != tenant_id` and return 404 (services/tenants.py:790-792, "
        ":827-829); :863 loads the current user's own row. Known debt: move the filter into the query."
    ),
    # ---- Children of a parent row already loaded with a tenant filter --------
    "delhivery_modules.DelhiveryModulesRepository.get_address": (
        "Loads the pickup address of a shipment that the service already loaded with a tenant "
        "filter (services/delhivery_modules.py:682), only to derive the GST place of supply."
    ),
    "delhivery_modules.DelhiveryModulesRepository.list_ticket_messages": (
        "Messages of a ticket that was loaded through get_ticket_by_identifier(tenant_id, identifier) "
        "(services/delhivery_modules.py:1215, :1256, :1292)."
    ),
    # ---- SQL fragments correlated to an outer tenant-filtered query ----------
    "delhivery_modules.DelhiveryModulesRepository._cod_settled_to_wallet_clause": (
        "Correlated EXISTS fragment; only used inside remittance queries that filter tenant_id."
    ),
    "wallet.WalletRepository._went_through_rto_clause": (
        "Correlated EXISTS fragment on the outer (tenant-filtered) shipment row."
    ),
    "wallet.WalletRepository._cod_payout_expression": (
        "Column expression (CASE) used inside tenant-filtered COD queries; selects no rows itself."
    ),
    "wallet.WalletRepository._attach_user_emails": (
        "Looks up emails only for user ids taken from rows the caller already loaded with a "
        "tenant filter; adds a display column, never new rows."
    ),
    "dashboard.DashboardRepository._activity_new_status": (
        "JSON column expression; used inside dashboard queries that apply _scope_filters (tenant)."
    ),
    "dashboard.DashboardRepository._json_rows": (
        "JSON row-expansion helper used inside scope-filtered dashboard queries."
    ),
    "manifests.ManifestRepository._shipment_eager_options": (
        "Returns selectinload() loader options; runs no query by itself."
    ),
    "appointments.<module>._delivery_address_exists": (
        "Correlated EXISTS on the outer shipment's delivery address; only used inside "
        "list_tab/tab_counts, which apply _scope_filters (tenant)."
    ),
    "exceptions.<module>._awaiting_ops_clause": (
        "Correlated EXISTS on activities of the outer shipment row; only used inside exception "
        "queries that apply _scope_filters(tenant_id, is_b2b, user_id)."
    ),
    "shipments.<module>.held_from_clause": (
        "Correlated scalar subquery on activities of the outer shipment row; only used inside "
        "queries that filter tenant_id (get_held_from_status, exception list/summary/detail)."
    ),
    "health.<module>.database_is_reachable": (
        "Readiness probe `SELECT 1`: reads no table and no tenant data (G-06)."
    ),
}


# --- AST model -------------------------------------------------------------


@dataclass(frozen=True)
class RepoMethod:
    """One repository method (or module-level function) found by the scanner."""

    module: str
    owner: str
    node: FuncNode
    scope_types_with_tenant: FrozenSet[str]

    @property
    def key(self) -> str:
        """Allow-list key `<module>.<Class>.<method>`."""
        return f"{self.module}.{self.owner}.{self.node.name}"


def _param_names(node: FuncNode) -> List[str]:
    """Positional + keyword-only parameter names, without self/cls."""
    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    return [a.arg for a in args if a.arg not in SELF_PARAMS]


def _param_annotation(node: FuncNode, name: str) -> Optional[str]:
    """Returns the simple annotation name of parameter `name` (e.g. `AppointmentScope`)."""
    for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
        if arg.arg == name and isinstance(arg.annotation, ast.Name):
            return arg.annotation.id
    return None


def _body_nodes(node: FuncNode) -> Iterator[ast.AST]:
    """Walks the function body (not its signature or decorators)."""
    for stmt in node.body:
        yield from ast.walk(stmt)


def _loaded_names(node: FuncNode) -> Set[str]:
    """Every bare name read in the body."""
    return {
        n.id for n in _body_nodes(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }


def _reads_param_entity_attr(node: FuncNode, params: List[str]) -> bool:
    """True when the body reads `<param>.tenant_id` or `<param>.id` for one of its parameters."""
    for n in _body_nodes(node):
        if (
            isinstance(n, ast.Attribute)
            and n.attr in ENTITY_SCOPE_ATTRS
            and isinstance(n.value, ast.Name)
            and n.value.id in params
        ):
            return True
    return False


def _is_session_receiver(value: ast.AST) -> bool:
    """True for `session`, `self.session`, `self._session`, `db` receivers."""
    if isinstance(value, ast.Name):
        return value.id in SESSION_NAMES
    return isinstance(value, ast.Attribute) and value.attr in SESSION_NAMES


def _runs_or_builds_query(node: FuncNode) -> bool:
    """True when the body builds (select / update / delete / insert / text) or executes a query."""
    for n in _body_nodes(node):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if isinstance(func, ast.Name) and func.id in QUERY_BUILDER_CALLS:
            return True
        if (
            isinstance(func, ast.Attribute)
            and func.attr in SESSION_QUERY_METHODS
            and _is_session_receiver(func.value)
        ):
            return True
    return False


def _scope_types_with_tenant(tree: ast.Module) -> FrozenSet[str]:
    """Names of classes in the module that declare a `tenant_id` field (NamedTuple/dataclass)."""
    names: Set[str] = set()
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for stmt in cls.body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == TENANT_FIELD
            ):
                names.add(cls.name)
    return frozenset(names)


def iter_repository_methods() -> Iterator[RepoMethod]:
    """Yields every method of every class plus every module-level function in app/repositories."""
    for path in sorted(REPOSITORIES_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scope_types = _scope_types_with_tenant(tree)
        for top in tree.body:
            if isinstance(top, ast.ClassDef):
                for item in top.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield RepoMethod(path.stem, top.name, item, scope_types)
            elif isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield RepoMethod(path.stem, "<module>", top, scope_types)


# --- Classification --------------------------------------------------------


def classify(method: RepoMethod) -> Optional[str]:
    """
    Returns None when the method is provably tenant-safe, else a failure reason.

    Args:
        method: The scanned repository method.

    Returns:
        None for a pass; a human-readable reason for a violation.
    """
    node = method.node
    if node.name == "__init__" or method.key in ALLOW_LIST:
        return None
    params = _param_names(node)
    loaded = _loaded_names(node)

    if TENANT_PARAM in params:
        if TENANT_PARAM in loaded:
            return None
        return "accepts `tenant_id` but never reads it (the filter is missing)"

    if SCOPE_PARAM in params and SCOPE_PARAM in loaded:
        annotation = _param_annotation(node, SCOPE_PARAM)
        if annotation is None or annotation in method.scope_types_with_tenant:
            return None
        return f"`scope: {annotation}` has no `tenant_id` field"

    if _reads_param_entity_attr(node, params):
        return None

    if not _runs_or_builds_query(node):
        return None

    return "runs or builds a query without a tenant_id parameter, a tenant scope or an entity tenant"


# --- Tests -----------------------------------------------------------------


def test_repositories_directory_is_scanned() -> None:
    """Guards against a moved directory making the guard pass vacuously."""
    methods = list(iter_repository_methods())
    assert REPOSITORIES_DIR.is_dir(), REPOSITORIES_DIR
    assert len(methods) >= 50, f"Only {len(methods)} repository methods found in {REPOSITORIES_DIR}"


def test_every_repository_query_is_tenant_scoped() -> None:
    """Fails when a repository method runs a query that cannot be shown to be tenant-scoped."""
    violations = [
        f"{m.key} (line {m.node.lineno}): {reason}"
        for m in iter_repository_methods()
        if (reason := classify(m)) is not None
    ]
    assert not violations, (
        "Repository methods without tenant isolation (AGENTS §5). Add a `tenant_id` filter, or, "
        "for a genuinely global lookup, add an ALLOW_LIST entry with the reason:\n  "
        + "\n  ".join(violations)
    )


def test_scope_filter_helpers_compare_tenant_id() -> None:
    """Every `_scope_filters(scope)` helper (rule 2) must compare `scope.tenant_id`."""
    helpers = [
        m
        for m in iter_repository_methods()
        if m.node.name == SCOPE_FILTER_HELPER and SCOPE_PARAM in _param_names(m.node)
    ]
    assert helpers, "Expected at least one _scope_filters helper (appointments, dashboard)"
    missing = [
        m.key
        for m in helpers
        if not any(
            isinstance(n, ast.Attribute)
            and n.attr == TENANT_FIELD
            and isinstance(n.value, ast.Name)
            and n.value.id == SCOPE_PARAM
            for n in _body_nodes(m.node)
        )
    ]
    assert not missing, f"_scope_filters helpers that do not filter by scope.tenant_id: {missing}"


def test_allow_list_has_no_stale_entries() -> None:
    """An allow-list key must still name an existing method, so exemptions cannot linger."""
    existing = {m.key for m in iter_repository_methods()}
    stale = sorted(set(ALLOW_LIST) - existing)
    assert not stale, f"Stale ALLOW_LIST entries (method renamed or removed): {stale}"


@pytest.mark.parametrize("key", sorted(ALLOW_LIST))
def test_allow_list_entries_are_justified(key: str) -> None:
    """Each exemption carries a real written reason."""
    assert len(ALLOW_LIST[key].strip()) >= 30, f"ALLOW_LIST[{key!r}] needs a real justification"


def test_classifier_catches_an_unscoped_query() -> None:
    """Self-test: a synthetic unscoped by-id query must be reported, a scoped one must pass."""
    source = (
        "class FakeRepository:\n"
        "    async def bad(self, shipment_id):\n"
        "        return await self.session.get(Pickup, shipment_id)\n"
        "    async def ignored(self, shipment_id, tenant_id):\n"
        "        return (await self.session.exec(select(Pickup).where(Pickup.id == shipment_id))).first()\n"
        "    async def good(self, shipment_id, tenant_id):\n"
        "        stmt = select(Pickup).where(Pickup.id == shipment_id, Pickup.tenant_id == tenant_id)\n"
        "        return (await self.session.exec(stmt)).first()\n"
        "    async def persist(self, row):\n"
        "        self.session.add(row)\n"
        "        await self.session.commit()\n"
    )
    tree = ast.parse(source)
    cls = tree.body[0]
    assert isinstance(cls, ast.ClassDef)
    results = {
        fn.name: classify(RepoMethod("fake", "FakeRepository", fn, frozenset()))
        for fn in cls.body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert results["bad"] is not None
    assert results["ignored"] is not None
    assert results["good"] is None
    assert results["persist"] is None
