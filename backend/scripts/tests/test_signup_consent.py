"""
Pure unit tests for the signup consent gate (C-08): `/auth/signup` must refuse
a new account without the "I agree to the Terms and Privacy Policy and will not
ship prohibited items" checkbox, and must stamp `terms_accepted_at` +
`terms_version` into the Supabase `raw_user_meta_data` of the new account.

No DB and no FastAPI app: the repository is an in-memory fake (or a fake
session for the repository metadata merge), so these run without the pinned
test tenant.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from fastapi import HTTPException

from app.repositories.tenants import TenantRepository
from app.schemas.v1.tenants import PasswordSignupRequest
from app.services.tenants import (
    MIN_PASSWORD_LENGTH,
    SIGNUP_EMAIL_EXISTS_DETAIL,
    TERMS_CONSENT_REQUIRED_DETAIL,
    TERMS_VERSION,
    TenantService,
)

NEW_AUTH_USER_ID = "11111111-1111-1111-1111-111111111111"
SIGNUP_EMAIL = "New.Seller@Example.com"
SIGNUP_PASSWORD = "Secret-123"
FIXED_NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


class _FakeTenantRepo:
    """Records `create_auth_user_with_password` calls; email lookup is configurable."""

    def __init__(self, existing_email: bool = False) -> None:
        self.existing_email = existing_email
        self.create_calls: list[dict[str, Any]] = []

    async def get_auth_user_by_email(self, email: str) -> Optional[dict]:
        return {"id": "existing"} if self.existing_email else None

    async def create_auth_user_with_password(self, **kwargs: Any) -> Optional[str]:
        self.create_calls.append(kwargs)
        return NEW_AUTH_USER_ID


def _service(repo: _FakeTenantRepo) -> TenantService:
    """A TenantService whose user provisioning and token minting are stubbed."""
    service = TenantService(tenant_repo=repo)  # type: ignore[arg-type]

    async def fake_get_or_create_user(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(is_active=True)

    service.get_or_create_user = fake_get_or_create_user  # type: ignore[method-assign]
    service._mint_supabase_session = (  # type: ignore[method-assign]
        lambda auth_id, email, user: {"auth_id": auth_id, "email": email}
    )
    return service


def _payload(**overrides: Any) -> PasswordSignupRequest:
    fields = {"email": SIGNUP_EMAIL, "password": SIGNUP_PASSWORD, **overrides}
    return PasswordSignupRequest(**fields)


def test_consent_defaults_to_not_given() -> None:
    assert _payload().terms_accepted is False


def test_consent_metadata_records_time_and_version() -> None:
    meta = TenantService._signup_consent_metadata(
        _payload(terms_accepted=True), now=FIXED_NOW
    )
    assert meta == {
        "terms_accepted_at": "2026-10-30T12:00:00+00:00",
        "terms_version": TERMS_VERSION,
    }


def test_consent_metadata_rejects_missing_consent() -> None:
    with pytest.raises(HTTPException) as exc:
        TenantService._signup_consent_metadata(_payload(terms_accepted=False))
    assert exc.value.status_code == 400
    assert exc.value.detail == TERMS_CONSENT_REQUIRED_DETAIL


async def test_signup_rejects_short_password_under_min_length() -> None:
    assert MIN_PASSWORD_LENGTH == 8
    repo = _FakeTenantRepo()
    with pytest.raises(HTTPException) as exc:
        await _service(repo).signup_with_password(
            tenant=SimpleNamespace(),  # type: ignore[arg-type]
            payload=_payload(password="short77", terms_accepted=True),
        )
    assert exc.value.status_code == 400
    assert "at least 8 characters" in exc.value.detail
    assert repo.create_calls == []


async def test_signup_without_consent_creates_no_account() -> None:
    repo = _FakeTenantRepo()
    with pytest.raises(HTTPException) as exc:
        await _service(repo).signup_with_password(
            tenant=SimpleNamespace(), payload=_payload()  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 400
    assert repo.create_calls == []


async def test_existing_email_still_gets_409_before_consent_check() -> None:
    repo = _FakeTenantRepo(existing_email=True)
    with pytest.raises(HTTPException) as exc:
        await _service(repo).signup_with_password(
            tenant=SimpleNamespace(), payload=_payload()  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == SIGNUP_EMAIL_EXISTS_DETAIL
    assert repo.create_calls == []


async def test_signup_with_consent_stores_consent_metadata() -> None:
    repo = _FakeTenantRepo()
    result = await _service(repo).signup_with_password(
        tenant=SimpleNamespace(),  # type: ignore[arg-type]
        payload=_payload(terms_accepted=True, full_name="New Seller"),
    )
    assert result == {"auth_id": NEW_AUTH_USER_ID, "email": "new.seller@example.com"}
    assert len(repo.create_calls) == 1
    extra = repo.create_calls[0]["extra_user_metadata"]
    assert extra["terms_version"] == TERMS_VERSION
    accepted_at = datetime.fromisoformat(extra["terms_accepted_at"])
    assert accepted_at.tzinfo is not None


class _FakeResult:
    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> dict:
        return {"id": NEW_AUTH_USER_ID}


class _FakeSession:
    """Captures the bound parameters of the auth.users INSERT."""

    def __init__(self) -> None:
        self.params: dict[str, Any] = {}

    async def execute(self, _stmt: Any, params: dict[str, Any]) -> _FakeResult:
        self.params = params
        return _FakeResult()

    async def flush(self) -> None:
        return None


async def test_repository_merges_consent_without_overriding_identity_keys() -> None:
    session = _FakeSession()
    repo = TenantRepository(session)  # type: ignore[arg-type]
    created = await repo.create_auth_user_with_password(
        email=SIGNUP_EMAIL,
        password=SIGNUP_PASSWORD,
        extra_user_metadata={
            "terms_version": TERMS_VERSION,
            "terms_accepted_at": FIXED_NOW.isoformat(),
            "email": "attacker@example.com",
            "email_verified": "no",
        },
    )
    assert created == NEW_AUTH_USER_ID
    user_meta = json.loads(session.params["user_meta"])
    assert user_meta["terms_version"] == TERMS_VERSION
    assert user_meta["terms_accepted_at"] == FIXED_NOW.isoformat()
    assert user_meta["email"] == "new.seller@example.com"
    assert user_meta["email_verified"] is True
