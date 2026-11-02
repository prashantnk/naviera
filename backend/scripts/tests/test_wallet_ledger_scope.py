"""
Regression tests for wallet ledger visibility.

Owner / Admin approve payments and Read-Only staff audit them, so all three
must read the tenant-wide ledger (every user's transactions). Every other role,
including Operations / Support staff and customers, sees only their own wallet.
"""
import uuid

import pytest

from app.core.permissions import can_view_tenant_finance
from app.models.tenants import User, UserRole
from app.services.wallet import WalletService

TENANT_WIDE_ROLES = (UserRole.owner, UserRole.admin, UserRole.read_only_user)
OWN_WALLET_ROLES = (
    UserRole.operations_user,
    UserRole.support_user,
    UserRole.customer,
)


def _user(role: UserRole) -> User:
    """Builds an in-memory user with the given role (no DB row needed)."""
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email=f"{role.value}@example.com",
        supabase_user_id=f"test:{uuid.uuid4()}",
        role=role,
    )


@pytest.mark.parametrize("role", TENANT_WIDE_ROLES)
def test_finance_viewers_read_whole_tenant_ledger(role: UserRole) -> None:
    viewer = _user(role)
    assert can_view_tenant_finance(viewer)
    assert WalletService._resolve_ledger_scope(viewer, None) is None


@pytest.mark.parametrize("role", TENANT_WIDE_ROLES)
def test_finance_viewers_can_narrow_to_one_user(role: UserRole) -> None:
    viewer = _user(role)
    target_user_id = uuid.uuid4()
    assert WalletService._resolve_ledger_scope(viewer, target_user_id) == target_user_id


@pytest.mark.parametrize("role", OWN_WALLET_ROLES)
def test_other_roles_only_see_own_wallet(role: UserRole) -> None:
    caller = _user(role)
    assert not can_view_tenant_finance(caller)
    assert WalletService._resolve_ledger_scope(caller, None) == caller.id
    # A forged `?user_id=` must never widen the scope for non-finance roles.
    assert WalletService._resolve_ledger_scope(caller, uuid.uuid4()) == caller.id
