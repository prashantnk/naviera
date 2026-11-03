# Naviera Backend 🚢

FastAPI backend of the Naviera logistics platform: Python 3.11, SQLModel, Alembic, PostgreSQL on Supabase
(through PgBouncer, port 6543). Multi-tenant: every repository query filters by `tenant_id`.

Operational procedures (fork bootstrap, deploy order, migrations, golden suite, live wipe, go-live checklist)
live in [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md).

---

## Layout

| Path | Role (Spring analogy) |
|---|---|
| `app/api/v1/endpoints/` | Route controllers + dependency injection (`@RestController`) |
| `app/services/pricing/` | Multi-carrier pricing package (`quote_service.py`, `booking.py`, `sell_price.py`, `carrier_billing.py`, `delhivery.py` / `delhivery_client.py` for B2C, `delhivery_b2b.py` / `delhivery_b2b_client.py` for B2B Cargo LTL, `prime.py` for Logismart Prime, plus `fake_delhivery.py` / `fake_delhivery_b2b.py` for `logismart-test`) |
| `app/services/` | Business logic and transactions (`@Service`). `repricing.py` (`RepricingService`) is the only writer of price columns; `shipment_lifecycle.py` owns the status-transition map (validate every status change through it); `integrity_audit.py` backs `GET /api/v1/wallet/audit-integrity` |
| `app/repositories/` | Database access (`JpaRepository`), always tenant-filtered |
| `app/models/`, `app/schemas/v1/` | SQLModel tables (`@Entity`) and request/response models (DTOs) |
| `app/core/` | Settings, DB engine (`NullPool` + PgBouncer-safe statement names), auth dependencies, `money.py` (Decimal, half-up to the paisa), `idempotency.py` |
| `alembic/versions/` | Migrations (raw SQL for enum changes) |
| `scripts/temporal_hooks_worker.py` | Background worker (all tenants) |
| `scripts/seed_prime_zones.py`, `scripts/import_prime_lanes.py`, `scripts/migrate_pricing_policy.py` | Logismart Prime zone/pincode seeder, Sheet1 lane importer, and pricing-policy migration (all dry run by default) |
| `scripts/seed_logismart_test.py`, `scripts/tenant_data_core.py`, `scripts/wipe_tenant_test_data.py`, `scripts/prepare_logismart_handover.py` | Test-tenant seed, shared FK-ordered delete core, one-time live wipe, demo cleanup (all dry run by default) |
| `scripts/run_golden.sh`, `scripts/tests/golden_journeys/`, `scripts/tests/ui_golden/` | Golden suite: API journeys and the Playwright click-through layer on `logismart-test` |
| `scripts/tests/` (other files) | Unit and integration tests |

## Setup

In GitHub Codespaces, `.devcontainer/post-create.sh` runs `poetry install --with e2e` (venv in `backend/.venv`) and
copies `.env.example` to `backend/.env` when it is missing; Codespaces secrets with the same names arrive as
environment variables, which take precedence over `.env`.

Manual setup from `naviera/backend/`:

```bash
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
cp .env.example .env        # fill in every value; do not add keys that are not Settings fields
poetry config virtualenvs.in-project true
poetry install --with e2e   # includes pypdf + pytest-playwright for PDF label & UI golden tests
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
poetry run python -m scripts.temporal_hooks_worker             # worker, second terminal
```

`backend/.env` must contain only fields of `Settings` in `app/core/config.py` (pydantic-settings rejects
unknown keys and the app will not start). Test and tooling variables (`GOLDEN_TENANT_SLUG`,
`GOLDEN_TEST_PASSWORD`, `UI_*`) are shell exports; see the bottom of [`.env.example`](.env.example).

## Migrations (Alembic)

The current chain, the five lean migrations (M-B1 to M-B4, M-C1), fork bootstrap notes and rollback notes are in
[runbook §3](../docs/RUNBOOK.md#3-migrations).

Writing a new migration:

1. Change the models in `app/models/`; import any **new** model module in `app/models/__init__.py` and
   `alembic/env.py` so autogenerate sees it.
2. `poetry run alembic revision --autogenerate -m "<what changes>"`, then review the file:
   - add `import sqlmodel.sql.sqltypes` if SQLModel types are used;
   - autogenerate does **not** detect enum value changes: write raw SQL (`ALTER TYPE ... ADD VALUE IF NOT
     EXISTS`) inside `op.get_context().autocommit_block()`; PostgreSQL cannot drop enum values, so the
     downgrade must map rows back and rebuild the type (see `7d5ebf60c105`);
   - dropping a table/column that owns an enum needs an explicit `DROP TYPE` in the downgrade;
   - new tables: `tenant_id NOT NULL` + FK + an index starting with `tenant_id`; money as `NUMERIC(12,2)`.
3. Keep migrations additive (expand only) so the running code keeps working; on a shared database apply one
   approved revision at a time with `poetry run alembic upgrade <revision>`; confirm with
   `poetry run alembic current`.

## Tests

```bash
poetry run ruff check .
poetry run pytest scripts/tests --collect-only -q    # no database
poetry run alembic upgrade head --sql > /dev/null    # offline migration SQL check, no database
GOLDEN_TEST_PASSWORD=... bash scripts/run_golden.sh  # full golden run on logismart-test (runbook §5)
```

`poetry run pytest scripts/tests` also runs DB-backed suites. They are guarded to the `logismart-test` tenant,
need the API on `:8000`, and must not run concurrently with another DB-touching session.

## Production quick reference (Render `naviera-backend` + GitHub Actions cron)

- **Web service (`naviera-backend`, `https://naviera-backend.onrender.com`):** build `pip install poetry && poetry install --only main`; start
  `poetry run uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log`.
- **Scheduled temporal hooks (`.github/workflows/temporal-hooks.yml`):** runs every 14 minutes (`*/14 * * * *`, plus `workflow_dispatch`) and calls `POST $NAVIERA_API_URL/api/v1/internal/temporal-hooks/run` with header `X-Cron-Secret: $CRON_SECRET` (`settings.CRON_SECRET`), running one idempotent iteration of `run_temporal_hooks_iteration()` and keeping the Free Render service warm (or run `poetry run python -m scripts.temporal_hooks_worker` if using a dedicated worker).
- **Database:** `DATABASE_URL` and `ALEMBIC_DATABASE_URL` use the Supabase pooler (port `6543`) with the password
  URL-encoded (`$` → `%24`). `DB_ECHO_LOG=False`.
- **Telemetry (Logfire):** auto-tracing limited to `app.api`, `app.services`, `app.repositories`; `/health` is
  filtered from Uvicorn logs.
