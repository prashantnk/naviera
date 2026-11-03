---
name: release-deploy
description: Guides the release pipeline from dev to master, Render and Vercel environment configuration, post-deploy verification, and rollback procedures.
---

# Release & Production Deployment Skill (`release-deploy`)

Use this skill when preparing a release from `dev` to `master`, checking Render (FastAPI API + background worker) and Vercel (Next.js frontend) environment variables, running post-deploy production smoke checks, or executing a rollback.

## 1. Release Pipeline Overview (`dev` $\rightarrow$ PR $\rightarrow$ `master`)

Naviera deploys automatically from `master`:
- **Backend API & Temporal Worker (Render):** Pushing to `master` builds and deploys the FastAPI service (`https://naviera-api.onrender.com`) and the background worker (`poetry run python -m scripts.temporal_hooks_worker`).
- **Frontend Web App (Vercel):** Pushing to `master` builds and deploys the Next.js 16 edge-dynamic monolith (`https://naviera.com`, `https://logismart.naviera.com`).

---

## 2. Pre-Release Checklist (On `dev`)

1. **Run the Pre-Merge Verification Gate:**
   ```bash
   export GOLDEN_TEST_PASSWORD="<test-account-password>"
   bash backend/scripts/run_golden.sh --quick
   bash backend/scripts/run_golden.sh --smoke
   ```
   *(And run full `bash backend/scripts/run_golden.sh` before major releases.)*
2. **Verify Pending Database Migrations:**
   Check if `dev` introduces new revisions under `backend/alembic/versions/`:
   ```bash
   git diff origin/master..dev -- backend/alembic/versions/
   ```
   If new migrations exist, obtain explicit user approval and apply one revision at a time (`poetry run alembic upgrade <revision>`) before promoting code that depends on the new schema (see [`docs/RUNBOOK.md`](../../../docs/RUNBOOK.md#3-migrations)).
3. **Verify Production Environment Variables (Render & Vercel):**
   Cross-check against [`docs/RUNBOOK.md`](../../../docs/RUNBOOK.md#1-environment--fresh-fork-bootstrap):
   - **Render (Backend):** `ENVIRONMENT=production`, `DATABASE_URL` (PgBouncer `:6543`), `ALEMBIC_DATABASE_URL` (`:5432`), `SUPABASE_URL`, `SECRET_KEY`, `SUPABASE_SERVICE_KEY`, `BACKEND_CORS_ORIGINS`, `FRONTEND_APP_URL`, `REVALIDATION_SECRET`, `DELHIVERY_B2C_TOKEN`, `DELHIVERY_B2C_BASE_URL=https://track.delhivery.com`, `DELHIVERY_TENANT_ID`, `DELHIVERY_LIVE_TENANT_SLUGS=logismart,logismart-test` (the test tenant prices on live Delhivery in the deployed env), `DELHIVERY_B2B_USERNAME`, `DELHIVERY_B2B_BASE_URL=https://ltl-clients-api.delhivery.com`. `DELHIVERY_FAKE_TENANT_SLUGS` must be **unset** on Render (test harness only; live vs fake is chosen per environment by these two keys, see RUNBOOK §1.3).
   - **Vercel (Frontend):** `BACKEND_API_URL=https://naviera-api.onrender.com`, `NEXT_PUBLIC_ROOT_DOMAIN=naviera.com`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `REVALIDATION_SECRET`.

---

## 3. Promoting `dev` $\rightarrow$ `master` & Realigning `dev`

1. **Open PR & Squash-Merge `dev` into `master`** (performed or approved by the human developer).
2. **Immediately Realign `dev` with `origin/master`:**
   Squash-merging creates a single new commit on `master`. To prevent divergent commit history on the next PR, realign `dev` right away:
   - **Option A — Clean Reset (Preferred when `dev` has no unmerged commits):**
     ```bash
     git fetch origin
     git checkout dev
     git reset --hard origin/master
     git push --force-with-lease origin dev
     ```
   - **Option B — Ours Merge (If preserving `dev` history without resetting):**
     ```bash
     git fetch origin
     git checkout dev
     git merge -s ours origin/master -m "chore: record master squash-merge"
     git push origin dev
     ```

---

## 4. Post-Deploy Production Verification

Once Render and Vercel finish deploying `master`, verify live health, security headers, CORS, public tenant config, and live rate quotes (see [`docs/RUNBOOK.md`](../../../docs/RUNBOOK.md#7-go-live-checklist-live-logismart-read-only)):

```bash
# 1. Liveness & DB readiness on Render:
curl -sS https://naviera-api.onrender.com/health
curl -sS https://naviera-api.onrender.com/health/ready

# 2. Public tenant config & frontend proxy on Vercel:
curl -sS https://naviera-api.onrender.com/api/v1/tenants/logismart/public | head -c 300
curl -sSI https://naviera.vercel.app/logismart | head -n 10
```

### 4.1 Post-Deploy Log & Telemetry Check
After running the post-deploy HTTP checks, inspect the 4 production telemetry streams for zero `5xx` responses or unhandled tracebacks:
1. **Render Logs (`naviera-backend`):** Check `Events` (verify the target commit is `Live` with no restart loop) and search `Logs` for `Traceback`, `ERROR`, `WARNING`, `502`, or `timeout`. *(Note: per-request access logs with `rndr-id` and duration are not available on the Render Free plan.)*
2. **Logfire EU (`logfire-eu.pydantic.dev`, project `prashantnk/naviera` — EU region):** Query `records` in the SQL Workbench for the deploy window (`http_response_status_code >= 500` or `level >= 'warn'`). Currently `logfire.instrument_fastapi` is active (FastAPI spans + `HTTPException` 4xx spans).
3. **Vercel Runtime Logs:** Check the **Logs** tab (Hobby plan retains the last `1h` of runtime logs) for `5xx`, timeouts, or edge/SSR exceptions.
4. **Supabase Postgres Logs:** Check **Logs ▸ Postgres** for unexpected database errors. *(Expected benign noise: `pg_pgrst_no_exposed_schemas` appears periodically because the PostgREST Data API exposed schemas are intentionally disabled for security.)*

---

## 5. Rollback Procedure

1. **Application Rollback (No Schema Change):**
   - **Vercel:** Open Vercel Dashboard $\rightarrow$ Deployments $\rightarrow$ select the previous green production deployment $\rightarrow$ **Promote to Production** (instant edge rollback).
   - **Render:** Open Render Dashboard $\rightarrow$ `naviera-api` (and worker) $\rightarrow$ Events / Deploys $\rightarrow$ **Rollback to this deploy** on the previous commit, or revert the merge commit on `master`.
2. **Database Migration Rollback (If a DDL Change Must Be Reverted):**
   - Obtain explicit human approval first.
   - Roll back the application code on Render/Vercel **before** running `poetry run alembic downgrade <previous-revision>` so the live API never queries dropped columns (see [`docs/RUNBOOK.md`](../../../docs/RUNBOOK.md#33-rollback-notes)).
