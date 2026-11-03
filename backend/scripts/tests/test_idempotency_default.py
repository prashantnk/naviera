"""
Pure unit tests for the test-only `IdempotencyKeyDefaultMiddleware` (`idempotency_default.py`):
keyless booking calls get a fresh key, explicit keys and other routes are untouched, and the
switch turns injection off for the missing-key contract test. No database, no Naviera app.
"""

import httpx
import idempotency_default
import pytest
from idempotency_default import IdempotencyKeyDefaultMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

BOOKING_PATH = "/api/v1/shipments"


async def _echo_key(request: Request) -> JSONResponse:
    return JSONResponse({"key": request.headers.get("idempotency-key")})


def _client() -> httpx.AsyncClient:
    app = Starlette(routes=[Route("/{path:path}", _echo_key, methods=["GET", "POST"])])
    app.add_middleware(IdempotencyKeyDefaultMiddleware)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_keyless_booking_gets_a_fresh_key_each_time() -> None:
    async with _client() as client:
        first = (await client.post(BOOKING_PATH, json={})).json()["key"]
        second = (await client.post(BOOKING_PATH, json={})).json()["key"]
    assert first.startswith("golden-") and second.startswith("golden-") and first != second


async def test_explicit_key_and_other_routes_are_untouched() -> None:
    async with _client() as client:
        own = await client.post(BOOKING_PATH, json={}, headers={"Idempotency-Key": "J55-race"})
        listing = await client.get(BOOKING_PATH)
        cancel = await client.post(f"{BOOKING_PATH}/abc/cancel", json={})
    assert own.json()["key"] == "J55-race"
    assert listing.json()["key"] is None
    assert cancel.json()["key"] is None


async def test_switch_off_leaves_the_request_keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(idempotency_default, "INJECT_DEFAULT_KEY", False)
    async with _client() as client:
        assert (await client.post(BOOKING_PATH, json={})).json()["key"] is None
