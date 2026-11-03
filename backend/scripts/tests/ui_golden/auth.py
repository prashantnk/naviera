"""
Per-role login once, then reuse a cached `storage_state` (plan E4).

Each canonical `logismart-test` account signs in through the real login form
(Supabase password flow) the first time it is needed. The resulting cookies +
localStorage are saved to `/tmp/naviera_ui_golden_<slug>_<account>.json`
(mode 0600) and reused by every later test until they are older than
`STORAGE_STATE_MAX_AGE_SECONDS`.

Guards reused from `golden_env`: the slug must be allow-listed (import time),
the tenant must be `environment == "test"`, and the email must be a canonical
test actor that is not a protected live identity (so the live owner can never
be logged in by this harness).
"""

import json
import os
import re
import stat
import time
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from golden_journeys.golden_env import (
    GOLDEN_TENANT_SLUG,
    assert_email_is_test_actor,
    assert_slug_allowed,
    load_accounts,
    mint_jwt,
)

# pytest (prepend import mode) puts `backend/scripts/tests` on sys.path and names
# the golden package `golden_journeys`; importing it by that same name shares one
# module object (account cache, run lock) with the golden API suites.
from app.core.config import settings as app_settings

from .browser_session import CdpSession
from .hud import StepBanner
from .pages.login_page import LoginPage
from .ui_config import (
    DESKTOP,
    PASSWORD_ENV_VAR,
    STORAGE_STATE_DIR,
    STORAGE_STATE_PREFIX,
    UiSettings,
)

STORAGE_STATE_MAX_AGE_SECONDS = 45 * 60
"""Supabase access tokens live 1 h; refresh well before that."""

_SAFE_NAME_RE = re.compile(r"[^a-z0-9]+")
_OWNER_ONLY_MODE = stat.S_IRUSR | stat.S_IWUSR


def storage_state_path(email: str, slug: str = GOLDEN_TENANT_SLUG) -> Path:
    """Returns `/tmp/naviera_ui_golden_<slug>_<email-safe>.json`."""
    safe = _SAFE_NAME_RE.sub("-", email.lower()).strip("-")
    return STORAGE_STATE_DIR / f"{STORAGE_STATE_PREFIX}_{slug}_{safe}.json"


def _is_fresh(path: Path, now: Optional[float] = None) -> bool:
    """True when the cached state exists and is younger than the max age."""
    if not path.exists():
        return False
    age = (now if now is not None else time.time()) - path.stat().st_mtime
    return age < STORAGE_STATE_MAX_AGE_SECONDS


def test_password() -> str:
    """
    Returns the shared test-account password from `GOLDEN_TEST_PASSWORD`.
    Returns an empty string if not set.
    """
    return os.getenv(PASSWORD_ENV_VAR, "")


# Not a pytest test despite the `test_` prefix.
test_password.__test__ = False  # type: ignore[attr-defined]


MINTED_SESSION_TTL_SECONDS = 3600
"""`expires_in` stamped on a minted browser session (refreshed long before, see max age)."""
MINTED_REFRESH_TOKEN = "golden-minted-no-refresh"
"""Placeholder: a minted session is never refreshed; the cache is rebuilt instead."""
SUPABASE_AUTH_ROLE = "authenticated"


def _supabase_storage_keys(tenant_slug: str) -> List[str]:
    """
    localStorage keys the frontend reads a session from (`frontend/src/lib/supabase.ts`):
    the per-tenant `sb-<slug>-auth-token` and supabase-js's default
    `sb-<project-ref>-auth-token`, the ref taken from `SUPABASE_URL` (no hard-coded project).
    """
    keys = [f"sb-{tenant_slug}-auth-token"]
    project_ref = (urlparse(app_settings.SUPABASE_URL).hostname or "").split(".")[0]
    if project_ref:
        keys.append(f"sb-{project_ref}-auth-token")
    return keys


async def _write_minted_storage_state(path: Path, email: str, settings: UiSettings) -> None:
    """
    Writes a Playwright storage state holding a backend-minted JWT for `email` (used when
    `GOLDEN_TEST_PASSWORD` is unset, so no Supabase password login is possible).
    """
    account = (await load_accounts())[email]
    token = account["headers"]["Authorization"].removeprefix("Bearer ")
    _write_session_state(path, token, str(account["supabase_user_id"]), email, settings)


def _write_session_state(
    path: Path, token: str, supabase_user_id: str, email: str, settings: UiSettings
) -> None:
    """Writes a storage state whose localStorage holds a supabase-js session for `token`."""
    session_value = json.dumps(
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": MINTED_SESSION_TTL_SECONDS,
            "expires_at": int(time.time()) + MINTED_SESSION_TTL_SECONDS,
            "refresh_token": MINTED_REFRESH_TOKEN,
            "user": {
                "id": supabase_user_id,
                "email": email,
                "aud": SUPABASE_AUTH_ROLE,
                "role": SUPABASE_AUTH_ROLE,
            },
        }
    )
    state = {
        "cookies": [],
        "origins": [
            {
                "origin": settings.frontend_url.rstrip("/"),
                "localStorage": [
                    {"name": key, "value": session_value}
                    for key in _supabase_storage_keys(settings.tenant_slug)
                ],
            }
        ],
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(path, _OWNER_ONLY_MODE)


def write_orphaned_storage_state(email: str, settings: UiSettings) -> Path:
    """
    Storage state for a canonical test `email` whose JWT `sub` has NO `user` row: what a tab
    holds after its user row was deleted (e.g. a sign-up wiped by the golden reset). The
    backend answers 403 "User does not have access to this tenant." Nothing is written to
    the database.

    Raises:
        GoldenEnvError: When the email or slug is not an allowed test actor/tenant.
    """
    assert_slug_allowed(settings.tenant_slug)
    orphan_sub = str(uuid.uuid4())
    token = mint_jwt(orphan_sub, email)  # refuses non-test actors
    path = storage_state_path(f"orphaned-{email}", settings.tenant_slug)
    _write_session_state(path, token, orphan_sub, email, settings)
    return path


async def ensure_storage_state(
    session: CdpSession, banner: StepBanner, email: str, force: bool = False
) -> Path:
    """
    Returns a fresh storage-state file for `email`, logging in through the UI if needed.
    When `GOLDEN_TEST_PASSWORD` is unset, a backend-minted session is written instead.

    Raises:
        GoldenEnvError: When the email or slug is not an allowed test actor/tenant.
    """
    assert_slug_allowed(session.settings.tenant_slug)
    assert_email_is_test_actor(email)
    path = storage_state_path(email, session.settings.tenant_slug)
    if not force and _is_fresh(path):
        return path
    
    password = test_password()
    if not password:
        await _write_minted_storage_state(path, email, session.settings)
        return path

    tab = await session.new_tab(DESKTOP)
    try:
        await banner.show_text(tab.page, f"Setup: sign in as {email}")
        login = LoginPage(tab.page, session.settings, banner)
        await login.open()
        await login.sign_in_with_password(email, password)
        await tab.context.storage_state(path=str(path))
        os.chmod(path, _OWNER_ONLY_MODE)
        tab.guard.assert_clean()
    finally:
        await tab.context.close()
    return path
