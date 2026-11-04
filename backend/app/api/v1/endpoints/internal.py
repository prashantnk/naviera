"""
Internal operational endpoints (scheduled temporal hooks trigger).

Replaces the paid Render cron job with an idempotent HTTP trigger called every 14 minutes
with `X-Cron-Secret` by Supabase `pg_cron` + `pg_net` (primary) and
`.github/workflows/temporal-hooks.yml` (best-effort backup), which also keeps the Free
Render web service warm.
"""

import logging
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Response, status

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
    response: Response,
    x_cron_secret: Optional[str] = Header(default=None, alias=CRON_SECRET_HEADER),
) -> Dict[str, Any]:
    """
    Runs one idempotent pass of `run_temporal_hooks_iteration()`.

    Disabled (returns 403) when `settings.CRON_SECRET` is unset or empty, or when the
    `X-Cron-Secret` header does not match in constant time. Returns the held counts
    (`appointments_held`, `eway_bills_held`, also logged under the same names on one
    `temporal_hooks_run` line); returns 500 with `failed_checks` when a check failed.
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
    counts = await temporal_hooks_worker.run_temporal_hooks_iteration()
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    failed_checks = [name for name, held in counts.items() if held is None]
    held_fields = " ".join(f"{name}={held}" for name, held in counts.items())
    log_msg = f"temporal_hooks_run {held_fields} duration_ms={duration_ms:.1f}"
    log_level = logging.ERROR if failed_checks else logging.INFO
    logger.log(log_level, log_msg)
    if uvicorn_root_logger.handlers and not uvicorn_root_logger.propagate:
        uvicorn_logger.log(log_level, log_msg)
    if failed_checks:
        # 500 makes the scheduler (GitHub Actions `curl --fail`, pg_net response log) record
        # the failure; the checks that succeeded are committed and reported.
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error", **counts, "failed_checks": failed_checks}
    return {"status": "ok", **counts}
