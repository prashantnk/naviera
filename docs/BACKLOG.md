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
- [ ] **GST document-number allocation lock timeout (`pg_advisory_xact_lock`)**: `lock_document_series` in `backend/app/services/gst_documents.py` uses `pg_advisory_xact_lock`, which can block bookings for 10–50 s when another session holds the same `tenant + FY + document_type` lock (e.g. a long-running test transaction or an idle-in-transaction connection on the same tenant). Set `lock_timeout` and `idle_in_transaction_session_timeout` on database sessions and keep test transactions short.

