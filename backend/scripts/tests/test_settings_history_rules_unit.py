"""
Settings history / restore rules (staff-settings journey audit 2026-11-01). Pure unit tests.

- A Settings "Restore" never rolls back the pricing policy (it has its own editor), nor KYC
  requests (runtime data), nor a configured invoice prefix.
- The history list hides rows a Settings restore can't undo (user role changes, pricing-only
  edits) and drops those labels from mixed rows.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional, Tuple

import pytest

from app.models.tenants import UserRole
from app.services.tenants import TenantService


def test_restore_keeps_current_pricing_policy_and_kyc() -> None:
    snapshot = {
        "brand": {"primary_color": "#111111"},
        "pricing_policy": {"delhivery_markup_percent": 50.0},
        "b2b_access_requests": {"old": {"status": "PENDING"}},
        "pricing_config": {"legacy": True},
    }
    current = {
        "brand": {"primary_color": "#dc2626"},
        "pricing_policy": {"delhivery_markup_percent": 0.0},
        "b2b_access_requests": {"u1": {"status": "APPROVED"}},
    }
    restored = TenantService._carry_forward_runtime_keys(dict(snapshot), current)
    assert restored["brand"] == {"primary_color": "#111111"}
    assert restored["pricing_policy"] == {"delhivery_markup_percent": 0.0}
    assert restored["b2b_access_requests"] == {"u1": {"status": "APPROVED"}}
    assert "pricing_config" not in restored


def test_restore_drops_pricing_policy_when_tenant_has_none_now() -> None:
    restored = TenantService._carry_forward_runtime_keys(
        {"pricing_policy": {"delhivery_markup_percent": 10.0}}, {}
    )
    assert "pricing_policy" not in restored


class _FakeRepo:
    def __init__(self, rows: List[Tuple[SimpleNamespace, Optional[str]]]) -> None:
        self._rows = rows

    async def list_settings_history(self, tenant_id: uuid.UUID):
        return self._rows


def _entry(version: int, sections: List[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        version=version,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        changed_sections=sections,
    )


@pytest.mark.asyncio
async def test_history_hides_rows_a_restore_cannot_undo() -> None:
    tenant_id = uuid.uuid4()
    admin = SimpleNamespace(id=uuid.uuid4(), role=UserRole.admin, tenant_id=tenant_id)
    rows = [
        (_entry(5, ["user_roles"]), "owner@logismart.in"),
        (_entry(4, ["pricing_policy"]), "owner@logismart.in"),
        (_entry(3, ["brand", "pricing_policy"]), "admin@logismart.in"),
        (_entry(2, ["contact"]), "admin@logismart.in"),
        (_entry(1, []), None),
    ]
    service = TenantService(tenant_repo=_FakeRepo(rows))  # type: ignore[arg-type]
    listed = await service.list_settings_history(tenant_id, admin)  # type: ignore[arg-type]
    assert [e.version for e in listed] == [3, 2, 1]
    assert listed[0].changed_sections == ["brand"]
    assert listed[1].changed_sections == ["contact"]
