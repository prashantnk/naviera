"""
Users page edits by an Owner/Admin (`TenantService._normalize_admin_user_edits`, staff-settings
journey audit 2026-11-01). Pure unit tests: no database.

Delhivery One `users`: team members see the whole account; Logismart's B2C / B2B scope only
restricts customers, so a staff member must never be locked out of B2B by the scope menu.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.tenants import ServiceScope, UserRole
from app.services.tenants import TenantService


def _target(role: UserRole) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role)


def _service() -> TenantService:
    return TenantService(tenant_repo=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "role",
    [
        UserRole.owner,
        UserRole.admin,
        UserRole.operations_user,
        UserRole.support_user,
        UserRole.read_only_user,
    ],
)
def test_staff_scope_is_always_both(role: UserRole) -> None:
    data = {"service_scope": ServiceScope.B2C}
    _service()._normalize_admin_user_edits(data, _target(role))
    assert data["service_scope"] == ServiceScope.BOTH


def test_customer_scope_is_kept() -> None:
    data = {"service_scope": ServiceScope.B2B}
    _service()._normalize_admin_user_edits(data, _target(UserRole.customer))
    assert data["service_scope"] == ServiceScope.B2B


def test_promoting_a_customer_to_staff_gives_both_flows() -> None:
    data = {"role": UserRole.support_user}
    _service()._normalize_admin_user_edits(data, _target(UserRole.customer))
    assert data["service_scope"] == ServiceScope.BOTH


def test_demoting_staff_to_customer_keeps_the_chosen_scope() -> None:
    data = {"role": UserRole.customer, "service_scope": ServiceScope.B2C}
    _service()._normalize_admin_user_edits(data, _target(UserRole.operations_user))
    assert data["service_scope"] == ServiceScope.B2C


def test_blank_name_is_ignored_and_names_are_trimmed() -> None:
    blank = {"full_name": "   "}
    _service()._normalize_admin_user_edits(blank, _target(UserRole.customer))
    assert "full_name" not in blank
    named = {"full_name": "  Ravi Kumar "}
    _service()._normalize_admin_user_edits(named, _target(UserRole.customer))
    assert named["full_name"] == "Ravi Kumar"


def test_phone_is_validated_and_normalised() -> None:
    data = {"phone": "98765 43210"}
    _service()._normalize_admin_user_edits(data, _target(UserRole.customer))
    assert data["phone"] == "9876543210"
    cleared = {"phone": ""}
    _service()._normalize_admin_user_edits(cleared, _target(UserRole.customer))
    assert cleared["phone"] is None
    with pytest.raises(HTTPException) as exc:
        _service()._normalize_admin_user_edits({"phone": "12ab"}, _target(UserRole.customer))
    assert exc.value.status_code == 400
