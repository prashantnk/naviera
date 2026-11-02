"""
Pure unit tests for the test-only `ResponseAuditMiddleware` (`response_audit.py`): the
server-only pricing fields are caught at any depth, staff pricing paths may return the
margin fields, non-JSON bodies pass through untouched. No database, no Naviera app.
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from response_audit import ResponseAuditMiddleware, forbidden_keys

STAFF_LANES_PATH = "/api/v1/pricing/prime-lanes"
CARRIER_BILLING_PATH = "/api/v1/shipments/5f0c/carrier-billing"


def _app(payload: object, media_type: str = "application/json") -> Starlette:
    """A one-route app returning `payload`, wrapped in the audit middleware."""

    async def endpoint(_request) -> Response:
        if media_type == "application/json":
            return JSONResponse(payload)
        return Response(content=payload, media_type=media_type)

    app = Starlette(routes=[Route("/{path:path}", endpoint)])
    app.add_middleware(ResponseAuditMiddleware)
    return app


async def _get(app: Starlette, path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path)


def test_forbidden_keys_found_at_any_depth() -> None:
    payload = {"items": [{"payment_details": {"pricing_breakdown": {"carrier_cost": {"gross": 1}}}}]}
    assert forbidden_keys(payload, "/api/v1/shipments") == [
        "$.items[0].payment_details.pricing_breakdown.carrier_cost",
        "$.items[0].payment_details.pricing_breakdown.carrier_cost.gross",
    ]


def test_margin_fields_allowed_only_on_staff_pricing_paths() -> None:
    lane = {"markup_percent": 20, "transporter_name": "X"}
    assert forbidden_keys(lane, f"{STAFF_LANES_PATH}/1") == []
    assert forbidden_keys(lane, CARRIER_BILLING_PATH) == []
    assert forbidden_keys(lane, "/api/v1/quotes") == ["$.markup_percent", "$.transporter_name"]
    assert forbidden_keys(lane, "/api/v1/shipments/5f0c") == ["$.markup_percent", "$.transporter_name"]
    assert forbidden_keys(lane, "/api/v1/shipments/5f0c", is_staff_caller=True) == ["$.markup_percent"]
    assert forbidden_keys({"transporter_name": None}, "/api/v1/shipments/5f0c") == []
    assert forbidden_keys({"carrier_cost": 1}, STAFF_LANES_PATH) == ["$.carrier_cost"]


def test_values_are_not_keys() -> None:
    assert forbidden_keys({"label": "gross", "notes": ["carrier_cost"]}, "/x") == []


async def test_middleware_fails_the_request_on_a_leak() -> None:
    with pytest.raises(AssertionError, match=r"\$\.gross"):
        await _get(_app({"gross": 10}), "/api/v1/quotes")


async def test_middleware_passes_clean_json_and_non_json_through() -> None:
    clean = await _get(_app({"total": "159.30"}), "/api/v1/quotes")
    assert clean.status_code == 200 and clean.json() == {"total": "159.30"}
    pdf = await _get(_app(b"%PDF-1.4 gross carrier_cost", "application/pdf"), "/label")
    assert pdf.content.startswith(b"%PDF")
