"""
Non-money setup steps of the UI journeys, done through the real HTTP API (plan E3).

The E3 UI layer clicks through the money screens only. Steps in between that are not
money screens (putting a booked AWB on a pickup request, reading the consignee's OTP the
way the merchant shares it) go through the same REST API the frontend uses, with the
canonical test account's token. Nothing here touches the database directly, so the
`DbOracle` stays strictly read-only.

Spring analogy: a `TestRestTemplate` helper used by Selenium tests for fixture data.
"""

from datetime import date
from typing import Any, Dict, Mapping, Sequence

from golden_journeys.golden_env import (
    ADMIN_EMAIL,
    headers,
    load_accounts,
    make_utr,
    read_otp_as_merchant,
)
import httpx

from .ui_fixtures import api_url

API_TIMEOUT_S = 120.0
"""The shared Supabase pooler is slow (~0.5 s per query); writes span many queries."""
PICKUP_SLOT = "10:00 - 14:00"
B2C_FLOW = "B2C"
MANIFESTS_PATH = "/api/v1/manifests"
REMITTANCES_PATH = "/api/v1/remittances"
SHIPMENTS_PATH = "/api/v1/shipments"


class ApiSetupError(AssertionError):
    """Raised when a setup call does not return the expected status."""


def _client() -> httpx.AsyncClient:
    """HTTP client bound to the backend under test."""
    return httpx.AsyncClient(base_url=api_url(), timeout=API_TIMEOUT_S)


async def _accounts() -> Mapping[str, Mapping[str, Any]]:
    """Minted JWT headers of the canonical `logismart-test` accounts (memoised)."""
    return await load_accounts()


async def create_b2c_pickup_request(
    merchant_email: str, pickup_address_id: str, shipment_ids: Sequence[str]
) -> Dict[str, Any]:
    """
    Puts OPEN B2C shipments on a new pickup request for today (Delhivery One:
    "Create pickup request"), as the merchant who booked them.

    Returns:
        The created pickup request JSON (`id`, `pickup_request_number`, ...).

    Raises:
        ApiSetupError: When the API does not answer 201.
    """
    accounts = await _accounts()
    async with _client() as client:
        resp = await client.post(
            MANIFESTS_PATH,
            headers=headers(accounts, merchant_email),
            json={
                "pickup_address_id": pickup_address_id,
                "scheduled_date": date.today().isoformat(),
                "time_slot": PICKUP_SLOT,
                "service_flow": B2C_FLOW,
                "is_blind_pickup": False,
                "shipment_ids": list(shipment_ids),
            },
        )
    if resp.status_code != 201:
        raise ApiSetupError(f"Create pickup request failed ({resp.status_code}): {resp.text}")
    return resp.json()


async def delivery_otp(merchant_email: str, shipment_id: str) -> str:
    """
    The consignee's 6-digit delivery OTP, read with the merchant's token (H-11: the rider
    must type it to mark the shipment delivered).
    """
    accounts = await _accounts()
    async with _client() as client:
        return await read_otp_as_merchant(client, accounts, merchant_email, shipment_id)


async def create_b2c_cod_remittance(shipment_id: str) -> Dict[str, Any]:
    """
    Finance closes a bank-UTR COD payout batch for one delivered COD shipment (Delhivery
    One: "COD remittance"), as the tenant admin. Amounts are computed by the backend.

    Returns:
        The created remittance JSON (`remittance_number`, `total_remittance`, ...).

    Raises:
        ApiSetupError: When the API does not answer 201.
    """
    accounts = await _accounts()
    admin_headers = headers(accounts, ADMIN_EMAIL)
    async with _client() as client:
        ship_resp = await client.get(f"{SHIPMENTS_PATH}/{shipment_id}", headers=admin_headers)
        if ship_resp.status_code != 200:
            raise ApiSetupError(
                f"Fetch shipment for remittance failed ({ship_resp.status_code}): {ship_resp.text}"
            )
        ship_data = ship_resp.json()
        pay = ship_data.get("payment_details") or {}
        expected_total = float(pay.get("cod_amount") or ship_data.get("shipment_total_value") or 0.0)
        resp = await client.post(
            REMITTANCES_PATH,
            headers=admin_headers,
            json={
                "shipment_ids": [shipment_id],
                "bank_utr": make_utr(),
                "expected_total": expected_total,
            },
        )
    if resp.status_code != 201:
        raise ApiSetupError(f"Create COD remittance failed ({resp.status_code}): {resp.text}")
    return resp.json()
