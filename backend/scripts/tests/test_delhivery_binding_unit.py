"""
Pure unit tests for the env-driven Delhivery binding (which client a tenant gets).

- `DELHIVERY_FAKE_TENANT_SLUGS` → the deterministic fake (test harness only; wins over live).
- `DELHIVERY_LIVE_TENANT_SLUGS`, or the id in `DELHIVERY_TENANT_ID` → the live client.
- Neither → None ("not connected").
- Live and fake answers never share a price-cache row (`LIVE|` key namespace).

No database: tenants are SimpleNamespaces and the price cache is an in-memory stand-in.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from app.core.config import settings
from app.schemas.v1.pricing import PricingPolicy
from app.services.pricing.delhivery import (
    LIVE_CACHE_NAMESPACE,
    PriceFreshness,
    delhivery_api_for,
    fetch_with_cache,
    tenant_cache_key,
)
from app.services.pricing.delhivery_b2b import (
    B2CFallbackDelhiveryB2BApi,
    delhivery_b2b_api_for,
)
from app.services.pricing.delhivery_b2b_client import LiveDelhiveryB2BApi
from app.services.pricing.delhivery_client import (
    LiveDelhiveryApi,
    is_fake_tenant,
    is_live_tenant,
)
from app.services.pricing.fake_delhivery import FakeDelhiveryApi
from app.services.pricing.fake_delhivery_b2b import FakeDelhiveryB2BApi
from app.services.pricing.policy import (
    delhivery_b2b_configured,
    delhivery_configured,
    to_read,
)
from app.services.pricing.types import PriceSource

TEST_SLUG = "logismart-test"
LIVE_SLUG = "logismart"
OTHER_SLUG = "acme"
RAW_KEY = "122001|110001|S|Delivered|Pre-paid|2000"


def _tenant(slug: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug=slug, settings={})


@pytest.fixture
def bindings(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Live B2C token, no B2B password, no id binding; each test sets the two slug lists."""
    monkeypatch.setattr(settings, "DELHIVERY_B2C_TOKEN", "b2c-token")
    monkeypatch.setattr(settings, "DELHIVERY_TENANT_ID", "")
    monkeypatch.setattr(settings, "DELHIVERY_B2B_USERNAME", "LOGISMARTB2BC")
    monkeypatch.setattr(settings, "DELHIVERY_B2B_PASSWORD", "")
    monkeypatch.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", "")
    monkeypatch.setattr(settings, "DELHIVERY_FAKE_TENANT_SLUGS", "")
    return monkeypatch


def test_harness_forces_the_fake_and_binds_nothing_live() -> None:
    assert settings.DELHIVERY_FAKE_TENANT_SLUGS == TEST_SLUG
    assert settings.DELHIVERY_LIVE_TENANT_SLUGS == ""
    assert isinstance(delhivery_api_for(_tenant(TEST_SLUG)), FakeDelhiveryApi)


def test_live_slug_gets_the_live_clients(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", f" {LIVE_SLUG} , {TEST_SLUG},")
    tenant = _tenant(TEST_SLUG)
    assert isinstance(delhivery_api_for(tenant), LiveDelhiveryApi)
    assert isinstance(delhivery_b2b_api_for(tenant), B2CFallbackDelhiveryB2BApi)
    assert delhivery_configured(tenant) and delhivery_b2b_configured(tenant)
    bindings.setattr(settings, "DELHIVERY_B2B_PASSWORD", "ltl-secret")
    assert isinstance(delhivery_b2b_api_for(tenant), LiveDelhiveryB2BApi)


def test_fake_slug_gets_the_fake_even_when_also_listed_live(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", f"{LIVE_SLUG},{TEST_SLUG}")
    bindings.setattr(settings, "DELHIVERY_FAKE_TENANT_SLUGS", TEST_SLUG)
    tenant = _tenant(TEST_SLUG)
    assert isinstance(delhivery_api_for(tenant), FakeDelhiveryApi)
    assert isinstance(delhivery_b2b_api_for(tenant), FakeDelhiveryB2BApi)
    assert to_read(tenant, PricingPolicy()).delhivery_configured is True
    assert isinstance(delhivery_api_for(_tenant(LIVE_SLUG)), LiveDelhiveryApi)


def test_unbound_tenant_is_not_connected(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", LIVE_SLUG)
    bindings.setattr(settings, "DELHIVERY_FAKE_TENANT_SLUGS", TEST_SLUG)
    tenant = _tenant(OTHER_SLUG)
    assert delhivery_api_for(tenant) is None
    assert delhivery_b2b_api_for(tenant) is None
    assert not delhivery_configured(tenant) and not delhivery_b2b_configured(tenant)


def test_tenant_id_binding_still_works(bindings: pytest.MonkeyPatch) -> None:
    tenant = _tenant(LIVE_SLUG)
    assert delhivery_api_for(tenant) is None
    bindings.setattr(settings, "DELHIVERY_TENANT_ID", f" {tenant.id} ")
    assert isinstance(delhivery_api_for(tenant), LiveDelhiveryApi)
    assert is_live_tenant(str(tenant.id))


def test_live_slug_without_credentials_is_not_connected(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", TEST_SLUG)
    bindings.setattr(settings, "DELHIVERY_B2C_TOKEN", "")
    tenant = _tenant(TEST_SLUG)
    assert delhivery_api_for(tenant) is None
    assert delhivery_b2b_api_for(tenant) is None


def test_fake_never_serves_a_live_tenant_even_if_misconfigured(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_FAKE_TENANT_SLUGS", LIVE_SLUG)
    assert is_fake_tenant(LIVE_SLUG)
    with pytest.raises(PermissionError):
        delhivery_api_for(_tenant(LIVE_SLUG))
    with pytest.raises(PermissionError):
        delhivery_b2b_api_for(_tenant(LIVE_SLUG))


def test_blank_slug_lists_bind_nothing(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", " , ")
    assert not is_live_tenant(str(uuid.uuid4()), "")
    assert not is_fake_tenant("")


# --- price cache: live and fake rows never mix ----------------------------------------------


class _MemoryCache:
    """In-memory stand-in for DelhiveryPriceCacheRepository."""

    def __init__(self) -> None:
        self.rows: Dict[str, SimpleNamespace] = {}

    async def get(self, tenant_id: Any, cache_key: str) -> Optional[SimpleNamespace]:
        return self.rows.get(cache_key)

    async def upsert(self, *, tenant_id, cache_key, request_params, response, fetched_at) -> None:
        self.rows[cache_key] = SimpleNamespace(response=response, fetched_at=fetched_at)


def test_cache_key_namespace_follows_the_binding(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", TEST_SLUG)
    tenant = _tenant(TEST_SLUG)
    assert tenant_cache_key(tenant, RAW_KEY) == f"{LIVE_CACHE_NAMESPACE}{RAW_KEY}"
    bindings.setattr(settings, "DELHIVERY_FAKE_TENANT_SLUGS", TEST_SLUG)
    assert tenant_cache_key(tenant, RAW_KEY) == RAW_KEY


async def test_live_tenant_never_reads_a_fake_written_row(bindings: pytest.MonkeyPatch) -> None:
    bindings.setattr(settings, "DELHIVERY_LIVE_TENANT_SLUGS", TEST_SLUG)
    tenant = _tenant(TEST_SLUG)
    cache = _MemoryCache()
    fake_answer = {"gross_amount": 135.0}
    cache.rows[RAW_KEY] = SimpleNamespace(response=fake_answer, fetched_at=datetime.now(timezone.utc).replace(tzinfo=None))
    live_answer = {"gross_amount": 61.22}

    async def live_call() -> Dict[str, Any]:
        return live_answer

    fetched = await fetch_with_cache(
        cache, tenant.id, tenant_cache_key(tenant, RAW_KEY), {}, PriceFreshness.QUOTE, live_call
    )
    assert fetched is not None and fetched.response == live_answer and fetched.source == PriceSource.LIVE
    assert cache.rows[RAW_KEY].response == fake_answer
    assert cache.rows[f"{LIVE_CACHE_NAMESPACE}{RAW_KEY}"].response == live_answer
