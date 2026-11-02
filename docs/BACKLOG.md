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

- [ ] **Delhivery B2B Cargo (LTL) API password**: until Delhivery issues it, "Delhivery B2B Cargo" shows "price
  unavailable" and Logismart Prime is the B2B option (RUNBOOK §1.3).
- [ ] **Event-driven architecture** (queues, Delhivery webhooks, customer notifications, automatic Delhivery
  booking): not needed while staff book on one.delhivery.com and update statuses in the app.
- [ ] **Logfire account / project cleanup**: the backend token belongs to EU project `prashantnk/naviera`
  (`logfire-eu.pydantic.dev`), while a new empty `starter-project` exists in the US region; keep one and consider a
  higher `install_auto_tracing` `min_duration` before traffic grows.
