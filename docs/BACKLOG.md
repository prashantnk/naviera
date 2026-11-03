# Naviera backlog (deferred after the Logismart lean MVP go-live)

Work we chose not to do for the first production deploy (2026-11). Each item says why it waits.
Operational detail: [`docs/RUNBOOK.md`](RUNBOOK.md). Architecture rules: `.agents/AGENTS.md`.

## Security

- [ ] **RLS + REVOKE migration on `public`**: enable row-level security on the 21 tables that still have it off and
  revoke `anon` / `authenticated` table grants (plus default privileges). Today the app never uses the Supabase Data
  API, so closing the exposed schemas in the dashboard is the immediate fix; this migration is the database-level
  backstop and needs its own approval (RUNBOOK §3).
- [ ] **Rotate `REVALIDATION_SECRET`**: the old value is in the public git history (commit `0b4344c`); the current
  value is kept on Vercel until it is rotated.
- [ ] **Rotate the Supabase database password**: it sat in plaintext scratch scripts; rotating it means updating
  `DATABASE_URL` / `ALEMBIC_DATABASE_URL` in Render, local `backend/.env` and Codespaces secrets at the same time.
- [ ] **Tighten Supabase Auth redirect URLs**: replace `https://*.vercel.app/**` with this project's own hosts and
  drop unused entries, so other Vercel apps cannot receive login redirects.
- [ ] **Storage tenant-path policies + `documents` public-URL bug**: any signed-in user can read or upload any
  tenant's files in the private `documents` bucket, and evidence photos are saved as public URLs that a private
  bucket does not serve.

## Hosting

- [ ] **Render Starter + move the API to Virginia (US East)**: the Free Ohio service sleeps after 15 minutes and sits
  in a different AWS region from Supabase (`us-east-1`), adding roughly 0.2 to 2.5 s per request.
- [ ] **Render cron for `scripts.temporal_hooks_worker`**: appointment-expiry and stale e-way-bill holds are not
  automatic until it runs (staff can put parcels on hold by hand meanwhile); Render cron jobs are paid only.
- [ ] **Vercel Pro**: the Hobby plan is for non-commercial use; Logismart is a paying business.
- [ ] **`logismart.in` custom-domain mapping in `frontend/src/middleware.ts`**: the middleware only recognises
  `*.naviera.com` subdomains, so a client domain would show the Naviera home page at `/`; the MVP uses
  `naviera.vercel.app/logismart`.

## Integrations and architecture

- [ ] **Delhivery B2B Cargo (LTL) API password**: while `DELHIVERY_B2B_PASSWORD` is empty, "Delhivery B2B Cargo" prices live via the B2C-token fallback (`B2CFallbackDelhiveryB2BApi` in `backend/app/services/pricing/delhivery_b2b_client.py`, using `DELHIVERY_B2C_TOKEN` with B2B volumetric divisor `4500` and `20 kg` minimum) alongside Logismart Prime. Setting `DELHIVERY_B2B_PASSWORD` once Delhivery issues it switches automatically to the native LTL `/ums/login` + `/freight/estimate` endpoint ([`RUNBOOK.md`](RUNBOOK.md#13-delhivery-api-token-b2c-and-b2b-cargo-credentials)).
- [ ] **Event-driven architecture** (queues, Delhivery webhooks, customer notifications, automatic Delhivery
  booking): not needed while staff book on one.delhivery.com and update statuses in the app.
- [ ] **Logfire account / project cleanup & SQLAlchemy/httpx instrumentation**: the backend token belongs to EU project `prashantnk/naviera`
  (`logfire-eu.pydantic.dev`), while a new empty `starter-project` exists in the US region; keep one and consider a
  higher `install_auto_tracing` `min_duration` before traffic grows. Currently Logfire captures FastAPI spans only (`logfire.instrument_fastapi`); add `logfire.instrument_sqlalchemy` and `logfire.instrument_httpx` so DB queries and outbound Delhivery API calls appear in trace timelines.
- [ ] **GST document-number allocation lock timeout (`pg_advisory_xact_lock`)**: `lock_document_series` in `backend/app/services/gst_documents.py` uses `pg_advisory_xact_lock`, which can block bookings for 10–50 s when another session holds the same `tenant + FY + document_type` lock (e.g. a long-running test transaction or an idle-in-transaction connection on the same tenant). Set `lock_timeout` and `idle_in_transaction_session_timeout` on database sessions and keep test transactions short.

## Testing and code hygiene

- [ ] **Fix and wire the 9 remaining standalone DB-integration test suites into `run_golden.sh` (`FULL_UNIT_SUITES`)**: 4 of the 13 savepoint-backed suites in `backend/scripts/tests/` (`test_appointments.py`, `test_production_readiness_guards.py`, `test_security_w1.py`, `test_user_onboarding_self_service.py`) are green and now wired into `FULL_UNIT_SUITES`. Fix and wire the remaining 9 suites (`test_b2b_onboarding_flow.py`, `test_dashboard_summary.py`, `test_exceptions_flow.py`, `test_manifest_flow.py`, `test_pretest_enhancements_g1_g6.py`, `test_reverse_bookings.py`, `test_settings_history.py`, `test_shipment_hardening.py`, and `test_wallet_and_otp_e2e.py`, each annotated in its module docstring with `"NOT wired…"` and the root cause: Prime test lanes missing fixture pincodes `411001`/`110001`/`560034`/`560035`, stale assertions where `COMPLETED` now requires a delivery OTP, settings rejecting unknown keys, B2B reverse disabled, and `test_wallet_and_otp_e2e.py` hanging).
- [ ] **Prune the 14 unreferenced backend symbols & regenerate `frontend/src/api_client`**: remove the 14 unreferenced symbols identified in the repo audit (`WalletService.reconcile_shipment_edit` and `WalletService.debit_weight_audit_delta` in `backend/app/services/wallet.py` which were superseded by `RepricingService`, `UserNotFoundException` in `backend/app/exceptions/definitions.py`, `has_wallet_refund_with_remark` in `backend/app/repositories/delhivery_modules.py`, `list_lane_rows` in `backend/app/repositories/prime_rates.py`, `TenantRepository.update_tenant` in `backend/app/repositories/tenants.py`, `RemittanceShipmentItem` and `BillingInvoiceLineItem` in `backend/app/schemas/v1/delhivery_modules.py`, `RateCalculationRequest` / `BulkRateCalculationRequest` / `BulkRateCalculationResponse` in `backend/app/schemas/v1/pickups.py`, `generate_tracking_id` in `backend/app/services/shipment.py`, `ManifestService._normalize_phone` in `backend/app/services/manifests.py`, and `RateLimiter.reset` in `backend/app/core/rate_limit.py`), and regenerate `frontend/src/api_client/` for `AdminOfflineCreditRequest` and `AdminShipmentChargeCreate`.
- [ ] **UI golden phase should run its own fake-env uvicorn on a separate port, so local `:8000` can be live for `logismart-test`**: deployed `logismart-test` prices on live Delhivery (`DELHIVERY_LIVE_TENANT_SLUGS=logismart,logismart-test` on Render), but the UI phase of `run_golden.sh` drives the shared Cloudtop `:8000` server, so the local `backend/.env` keeps `logismart-test` out of `DELHIVERY_LIVE_TENANT_SLUGS` to keep UI journeys deterministic (fake-only checks such as `FAKE_UNSERVICEABLE_PINS`) and within the 45 / 5 min price limit. Start a UI-only uvicorn with `DELHIVERY_FAKE_TENANT_SLUGS=logismart-test` on its own port and point the UI phase at it; then local `:8000` can bind `logismart-test` live too.
