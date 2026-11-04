"""pg_cron_temporal_hooks (reliable free 14-minute trigger for the temporal hooks)

GitHub Actions `schedule` is best-effort: on this repo `*/14 * * * *` fired only twice in
the first 9 hours (22:22Z and 02:34Z on 2026-11-03/04), so overdue appointments and stale
e-way bills were not held on time and the Free Render instance went to sleep between runs.

This revision schedules the same call from the database, which is always on:

1. Enables `pg_cron` (schema `pg_catalog`, as on Supabase) and `pg_net` (schema
   `extensions`; its functions live in schema `net`). Both are available on the Supabase
   Free plan and not exposed through the Data API.
2. Schedules job `naviera-temporal-hooks` on `*/14 * * * *` (UTC): an async `net.http_post`
   to the temporal-hooks endpoint with header `X-Cron-Secret`, timeout 120 s (Render Free
   cold start is ~50 s; the request reaches the API even if pg_net stops waiting).
3. The endpoint URL and the shared secret are read from Supabase Vault at run time
   (`vault.decrypted_secrets`, names below), so no secret or environment-specific value is
   stored in this file or in `cron.job.command`. Until both Vault secrets exist the job is a
   no-op (the `WHERE EXISTS` guard), so applying this revision is safe on its own.

Side effects: no table or data change. Outcomes are visible in `cron.job_run_details`
(the job ran) and `net._http_response` (HTTP status/body, kept 6 h by pg_net). On a
Postgres without these extensions (not Supabase) the revision logs a warning and does
nothing. Downgrade unschedules the job and keeps both extensions installed (dropping
`pg_cron` would also delete any job created from the Supabase dashboard).

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-04 04:00:00.000000

"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(f"alembic.runtime.migration.{revision}")

JOB_NAME = "naviera-temporal-hooks"
JOB_SCHEDULE = "*/14 * * * *"
"""Every 14 minutes: inside Render Free's 15-minute idle window, so it also keeps the API warm."""
URL_SECRET = "naviera_temporal_hooks_url"
"""Vault secret: full endpoint URL, e.g. https://naviera-backend.onrender.com/api/v1/internal/temporal-hooks/run."""
CRON_SECRET = "naviera_cron_secret"
"""Vault secret: the same value as the API's `CRON_SECRET` setting."""
HTTP_TIMEOUT_MS = 120_000
REQUIRED_EXTENSIONS = ("pg_cron", "pg_net")

JOB_COMMAND = f"""
SELECT net.http_post(
    url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = '{URL_SECRET}'),
    body := '{{}}'::jsonb,
    headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'X-Cron-Secret',
        (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = '{CRON_SECRET}')
    ),
    timeout_milliseconds := {HTTP_TIMEOUT_MS}
)
WHERE EXISTS (SELECT 1 FROM vault.decrypted_secrets WHERE name = '{URL_SECRET}')
  AND EXISTS (SELECT 1 FROM vault.decrypted_secrets WHERE name = '{CRON_SECRET}')
"""
"""Runs as the scheduling role (`postgres`); a no-op until both Vault secrets exist."""

UPGRADE_STATEMENTS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog",
    "CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions",
    # cron.schedule(name, ...) replaces an existing job of the same name (idempotent).
    f"SELECT cron.schedule('{JOB_NAME}', '{JOB_SCHEDULE}', $job${JOB_COMMAND}$job$)",
)
"""Executed in order by `upgrade()`."""

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    f"SELECT cron.unschedule(jobid) FROM cron.job WHERE jobname = '{JOB_NAME}'",
)
"""Removes the job; the extensions stay installed (see module docstring)."""


def _extensions_available() -> bool:
    """True when this Postgres ships both pg_cron and pg_net (Supabase does)."""
    available = op.get_bind().execute(
        sa.text("SELECT count(*) FROM pg_available_extensions WHERE name = ANY(:names)"),
        {"names": list(REQUIRED_EXTENSIONS)},
    ).scalar_one()
    return available == len(REQUIRED_EXTENSIONS)


def upgrade() -> None:
    """Enables pg_cron + pg_net and schedules the 14-minute temporal-hooks call."""
    if not _extensions_available():
        logger.warning("pg_cron/pg_net not available; temporal-hooks job not scheduled")
        return
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Unschedules the temporal-hooks job."""
    if not _extensions_available():
        return
    if not op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron')")
    ).scalar_one():
        return
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
