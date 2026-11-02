"""
Unit and HTTP tests for the Prime Lanes Sample CSV Template endpoint (`GET /pricing/prime-lanes/template.csv`,
`/pricing/prime-lanes/template-csv`, `/pricing/prime-lanes/template`) and Door vs Godown quote pricing.
"""

import csv
import io
import uuid
from types import SimpleNamespace
from typing import Any, List

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import pricing_prime
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.prime import PrimeZone
from app.models.tenants import UserRole
from app.repositories.prime_rates import LaneWithZones
from app.services.prime_admin import (
    LANE_CSV_COLUMNS,
    PrimeAdminService,
    get_prime_admin_service,
    parse_lanes_csv,
)

TENANT_ID = uuid.uuid4()


class _FakeTemplateAdminRepository:
    """In-memory repository for template + dry-run import checks."""

    def __init__(self, lanes: List[LaneWithZones] | None = None) -> None:
        self.lanes = lanes or []

    async def list_zones(self, tenant_id: uuid.UUID) -> List[PrimeZone]:
        return [
            PrimeZone(id=uuid.uuid4(), tenant_id=tenant_id, name="Delhi NCR"),
            PrimeZone(id=uuid.uuid4(), tenant_id=tenant_id, name="Mumbai"),
            PrimeZone(id=uuid.uuid4(), tenant_id=tenant_id, name="Bengaluru"),
            PrimeZone(id=uuid.uuid4(), tenant_id=tenant_id, name="Hyderabad"),
        ]

    async def list_lanes(self, tenant_id: uuid.UUID, *, active_only: bool = False) -> List[LaneWithZones]:
        return list(self.lanes)


def _user(role: UserRole) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), role=role)


def _client(role: UserRole = UserRole.admin) -> TestClient:
    app = FastAPI()
    app.include_router(pricing_prime.router, prefix="/pricing")
    app.dependency_overrides[get_current_active_user] = lambda: _user(role)
    app.dependency_overrides[get_tenant_from_header] = lambda: SimpleNamespace(id=TENANT_ID)
    app.dependency_overrides[get_prime_admin_service] = lambda: PrimeAdminService(
        _FakeTemplateAdminRepository()  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_template_csv_endpoints_return_downloadable_sample_csv() -> None:
    client = _client(UserRole.admin)
    for path in (
        "/pricing/prime-lanes/template.csv",
        "/pricing/prime-lanes/template-csv",
        "/pricing/prime-lanes/template",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"Expected 200 for {path}, got {response.status_code}"
        assert response.headers["content-type"].startswith("text/csv")
        assert 'filename="prime_lanes_template.csv"' in response.headers.get("content-disposition", "")

        reader = csv.DictReader(io.StringIO(response.text))
        assert tuple(reader.fieldnames or ()) == LANE_CSV_COLUMNS
        rows = list(reader)
        assert len(rows) == 2
        assert (rows[0]["origin_zone"], rows[0]["dest_zone"], rows[0]["mode"]) == (
            "Delhi NCR",
            "Mumbai",
            "SURFACE",
        )
        assert (rows[1]["origin_zone"], rows[1]["dest_zone"], rows[1]["mode"]) == (
            "Bengaluru",
            "Hyderabad",
            "SURFACE",
        )


def test_template_csv_round_trips_through_importer_dry_run() -> None:
    client = _client(UserRole.admin)
    template_resp = client.get("/pricing/prime-lanes/template.csv")
    assert template_resp.status_code == 200

    inputs, plan = parse_lanes_csv(template_resp.text)
    assert not plan.errors
    assert not plan.warnings
    assert len(inputs) == 2

    import_resp = client.post(
        "/pricing/prime-lanes/import?dry_run=true",
        content=template_resp.content,
        headers={"Content-Type": "text/csv"},
    )
    assert import_resp.status_code == 200
    assert import_resp.json() == {
        "created": 2,
        "updated": 0,
        "deactivated": 0,
        "errors": [],
        "warnings": [],
    }


def test_template_csv_rejects_customers_with_403() -> None:
    customer_client = _client(UserRole.customer)
    response = customer_client.get("/pricing/prime-lanes/template.csv")
    assert response.status_code == 403
