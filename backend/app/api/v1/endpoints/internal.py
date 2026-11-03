"""
Internal operational endpoints (scheduled temporal hooks trigger).

Replaces the paid Render cron job with an idempotent HTTP trigger called every 14 minutes
by `.github/workflows/temporal-hooks.yml` using `X-Cron-Secret`, which also keeps the Free
Render web service warm.
"""

import logging
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import settings
from scripts import temporal_hooks_worker

logger = logging.getLogger(__name__)
uvicorn_root_logger = logging.getLogger("uvicorn")
uvicorn_logger = logging.getLogger("uvicorn.error")

router = APIRouter()

CRON_SECRET_HEADER = "X-Cron-Secret"
FORBIDDEN_CRON_DETAIL = "Invalid or missing cron secret."


@router.post("/temporal-hooks/run")
async def run_temporal_hooks(
    x_cron_secret: Optional[str] = Header(default=None, alias=CRON_SECRET_HEADER),
) -> Dict[str, Any]:
    """
    Runs one idempotent pass of `run_temporal_hooks_iteration()`.

    Disabled (returns 403) when `settings.CRON_SECRET` is unset or empty, or when the
    `X-Cron-Secret` header does not match in constant time.
    """
    configured_secret = settings.CRON_SECRET.strip()
    provided_secret = (x_cron_secret or "").strip()
    if (
        not configured_secret
        or not provided_secret
        or not secrets.compare_digest(provided_secret, configured_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_CRON_DETAIL,
        )

    started_at = time.perf_counter()
    counts = await temporal_hooks_worker.run_temporal_hooks_iteration() or {}
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    appointments_held = int(counts.get("appointments_held", 0))
    eway_bills_held = int(counts.get("eway_bills_held", 0))
    log_msg = (
        f"temporal_hooks_run expired_appointments={appointments_held} "
        f"stale_eway_holds={eway_bills_held} duration_ms={duration_ms:.1f}"
    )
    logger.info(log_msg)
    if uvicorn_root_logger.handlers and not uvicorn_root_logger.propagate:
        uvicorn_logger.info(log_msg)
    return {
        "status": "ok",
        "appointments_held": appointments_held,
        "eway_bills_held": eway_bills_held,
    }
