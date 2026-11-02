"""
Readiness probe query (G-06). The only repository without a tenant: it touches no table.
Spring Boot Equivalent: a `HealthIndicator` that runs `SELECT 1` on the DataSource.
"""

import logging

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

READINESS_QUERY = "SELECT 1"


async def database_is_reachable(session: AsyncSession) -> bool:
    """
    Runs `SELECT 1` (no table, no tenant data).

    Returns:
        True when the database answered, False on any error (logged with its traceback).
    """
    try:
        await session.exec(text(READINESS_QUERY))  # type: ignore[call-overload]
    except Exception:  # noqa: BLE001 - readiness must report, never raise
        logger.exception("Readiness probe: database unreachable")
        return False
    return True
