"""
Conftest for the UI click-through golden layer (ship-readiness plan E3/E4).

1. Shadows the parent unit-test fixtures (`init_db_cache`, `db_session`,
   `global_dependency_overrides`) with no-ops: UI tests talk to the real running
   backend and never open mocked or rolled-back sessions (same pattern as
   `golden_journeys/conftest.py`).
2. Loads the browser fixtures from `ui_fixtures.py` only when Playwright is
   installed (dev group `e2e`). Without it, the test modules skip themselves via
   `pytest.importorskip`, so `pytest --collect-only` stays clean.
3. Marks every test here with `ui` (select with `-m ui`, exclude with `-m "not ui"`).
"""

from typing import AsyncIterator, List

import pytest

UI_MARKER = "ui: drives the visible Chrome over CDP (ship-readiness plan E3/E4)"

try:
    import playwright.async_api  # noqa: F401
except ImportError:  # pragma: no cover - depends on the installed dev group
    HAVE_PLAYWRIGHT = False
else:
    HAVE_PLAYWRIGHT = True
    from .ui_fixtures import (  # noqa: F401 - re-exported so pytest discovers them
        TabFactory,
        cdp_session,
        db_oracle,
        role_tabs,
        step_banner,
        ui_settings,
        ui_tabs,
        ui_tenant,
    )


def pytest_configure(config: pytest.Config) -> None:
    """Registers the `ui` marker."""
    config.addinivalue_line("markers", UI_MARKER)


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """Adds the `ui` marker to every collected test under this folder."""
    for item in items:
        if "ui_golden" in item.nodeid:
            item.add_marker(pytest.mark.ui)


@pytest.fixture(autouse=True, scope="session")
async def init_db_cache() -> AsyncIterator[None]:
    """No-op shadow: UI tests never use the mocked unit-test identity."""
    yield


@pytest.fixture
async def db_session() -> AsyncIterator[None]:
    """No-op shadow: UI tests never open a rolled-back write session."""
    yield None


@pytest.fixture(autouse=True)
async def global_dependency_overrides() -> AsyncIterator[None]:
    """No-op shadow: the UI talks to the real running backend."""
    yield
