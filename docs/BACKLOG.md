# Naviera backlog (deferred after the Logismart lean MVP go-live)

Work we chose not to do for the first production deploy (2026-11). Each item says why it waits.
Operational detail: [`docs/RUNBOOK.md`](RUNBOOK.md). Architecture rules: `.agents/AGENTS.md`.

## Needs a paid plan (user decision)

- [ ] **Render Starter + move the API to Virginia (US East)**: the Free Ohio service sleeps after 15 minutes and sits
  in a different AWS region from Supabase (`us-east-1`), adding roughly 0.2 to 2.5 s per request.
- [ ] **Vercel Pro**: the Hobby plan is for non-commercial use; Logismart is a paying business.

## Integrations and architecture

- [ ] **Delhivery B2B Cargo (LTL) API password**: while `DELHIVERY_B2B_PASSWORD` is empty, "Delhivery B2B Cargo" prices live via the B2C-token fallback (`B2CFallbackDelhiveryB2BApi` in `backend/app/services/pricing/delhivery_b2b_client.py`, using `DELHIVERY_B2C_TOKEN` with B2B volumetric divisor `4500` and `20 kg` minimum) alongside Logismart Prime. Setting `DELHIVERY_B2B_PASSWORD` once Delhivery issues it switches automatically to the native LTL `/ums/login` + `/freight/estimate` endpoint ([`RUNBOOK.md`](RUNBOOK.md#13-delhivery-api-token-b2c-and-b2b-cargo-credentials)).
- [ ] **Event-driven architecture** (queues, Delhivery webhooks, customer notifications, automatic Delhivery
  booking): not needed while staff book on one.delhivery.com and update statuses in the app.
- [ ] **Logfire account / project cleanup & SQLAlchemy/httpx instrumentation**: the backend token belongs to EU project `prashantnk/naviera`
  (`logfire-eu.pydantic.dev`), while a new empty `starter-project` exists in the US region; keep one and consider a
  higher `install_auto_tracing` `min_duration` before traffic grows. Currently Logfire captures FastAPI spans only (`logfire.instrument_fastapi`); add `logfire.instrument_sqlalchemy` and `logfire.instrument_httpx` so DB queries and outbound Delhivery API calls appear in trace timelines.
- [ ] **DB-backed unit suites hold GST series locks on the shared tenant**: `scripts/tests/conftest.py` runs each DB test in one outer transaction on `logismart-test`, so a test that issues a GST document keeps that series' advisory lock until the test ends. Since BUG-03, other bookings wait at most 20 s and then get a retryable 503, but they still fail while the suite runs. Don't run `FULL_UNIT_SUITES` while anyone is doing manual/UI QA on the same database, or give the savepoint fixture its own tenant.

## Notion Issue Tracker — Phase-2 Deferred Enhancements

The following 8 items from the Notion `Issue Tracking` database (`281e0e40-6a02-8090-add6-000b141623ce`) were audited during the Release-5 handover triage and deferred to Phase 2:

- [ ] **Notion `#16` — Bulk Shipment Creation via CSV (`POST /api/v1/shipments/bulk`)** (`313e0e40-6a02-802e-8ae6-f4d467b69982`):
  - **Context:** Bulk NDR actions (`POST /api/v1/exceptions/bulk-action`) and Prime Lanes CSV upload (`POST /api/v1/pricing/prime-lanes/import`) are live in MVP, while B2B/B2C merchants uploading 500+ orders at once via CSV need a batch shipment booking endpoint rather than calling `POST /api/v1/shipments` one row at a time.
  - **Phase-2 Plan:** Add `POST /api/v1/shipments/bulk` accepting `List[PickupCreate]` (up to 500 rows) with partial-success execution, per-row validation/wallet/pricing error reporting (`BulkShipmentCreateResponse`), and a CSV order import wizard in `OrdersWorkspace`.
- [ ] **Notion `#13` — Full-Text / Elasticsearch Indexing for Global Search** (`317e0e40-6a02-8026-b1fb-ff6071a07e25`):
  - **Context:** Order, pickup request, exception, invoice, and address search in MVP uses PostgreSQL `ILIKE` queries and client-side generic omni-search filtering (`matchesOrderSearch` in `orders-workspace.tsx` and `matchesManifestSearch` in `pickup-requests-list.tsx`).
  - **Phase-2 Plan:** Add PostgreSQL GIN `tsvector` / `pg_trgm` indexes (or Elasticsearch/Typesense if shipment volume exceeds 1M+ rows) backing a server-side `search` query parameter on `GET /api/v1/shipments`.
- [ ] **Notion `#07` — Shared Redis Cache & Distributed Rate Limiter** (`294e0e40-6a02-8025-b65e-de5633bf1b2d`):
  - **Context:** Auth rate limiting (`SlidingWindowLimiter` in `backend/app/core/rate_limit.py`) is in-memory for the single-instance Render MVP, and live Delhivery rate quotes are cached for 24h in PostgreSQL (`delhivery_price_cache`).
  - **Phase-2 Plan:** When scaling horizontally to multiple FastAPI web workers, back `SlidingWindowLimiter` and hot rate-quote / tenant-settings caches with managed Redis (Upstash / Render Key Value).
- [ ] **Notion `#02` & `#08` — GitHub Actions Pre-Deployment CI Pipeline (`ruff`, `tsc`, `eslint`, `vitest`, `pytest`)** (`294e0e40-6a02-800d-8b15-ea4acbd469bf`, `294e0e40-6a02-8013-89af-cb61959d3272`):
  - **Context:** `bash backend/scripts/run_golden.sh --quick` runs all static analyzers (`ruff check .`, `npx tsc --noEmit`, `npx eslint src --max-warnings=0`, `npm run test:audit`) and 38 pure unit test suites locally before release, while `.github/workflows/` currently runs `temporal-hooks.yml`.
  - **Phase-2 Plan:** Add `.github/workflows/ci.yml` to run `run_golden.sh --quick` automatically on every push to `dev` and every PR targeting `master`.
- [ ] **Notion `#09` — GitHub Branch Protection Ruleset on `master`** (`294e0e40-6a02-803e-89cc-febc46dbf117`):
  - **Context:** Releases follow `dev -> PR -> squash-merge to master` (`.agents/AGENTS.md` §8 and `docs/RUNBOOK.md`).
  - **Phase-2 Plan:** Once `.github/workflows/ci.yml` (`#02` / `#08`) is enabled, configure a GitHub Branch Protection ruleset on `master` requiring PR review and passing `ci.yml` status checks before merge.
- [ ] **Notion `#04` — Root `Makefile` Developer Task Runner** (`294e0e40-6a02-8027-b6aa-d17008276b94`):
  - **Context:** Developer workflows are currently invoked via `bash backend/scripts/run_golden.sh [--quick|--smoke]` and `poetry` / `npm` CLI commands documented in `docs/DEVELOPMENT.md`.
  - **Phase-2 Plan:** Add an optional root `Makefile` aliasing common targets (`make dev`, `make quick`, `make smoke`, `make golden`, `make codegen`).
- [ ] **Notion `#05` — Production `Dockerfile` & `docker-compose.yml` for Self-Hosted Deployments** (`294e0e40-6a02-801b-b2ae-da8c54f29f81`):
  - **Context:** Production deploys natively on Vercel (Next.js) and Render (Python Poetry web service).
  - **Phase-2 Plan:** Provide multi-stage `backend/Dockerfile`, `frontend/Dockerfile`, and `docker-compose.yml` if enterprise tenants require self-hosted or VPC-isolated container deployments.

