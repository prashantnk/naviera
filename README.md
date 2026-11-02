# Naviera Monorepo 🚢

Naviera is a multi-tenant logistics SaaS platform (first client: **Logismart**, modelled on Delhivery One).
It is an **Edge-Dynamic Monolith**: one Next.js frontend and one FastAPI backend serve every tenant, with
strict per-tenant data isolation (`tenant_id` on every query).

## 🏗️ Architecture

- **Frontend:** Next.js 15 (App Router), Tailwind CSS + runtime CSS variables per tenant, shadcn/ui,
  React Hook Form + zod, TanStack Table/Query. `middleware.ts` maps a subdomain or path segment to
  `/[tenant_slug]/...`.
- **Backend:** Python 3.11, FastAPI, SQLModel, Alembic; layered endpoints → services → repositories.
- **Database:** PostgreSQL on Supabase through PgBouncer (`asyncpg`, `NullPool`).
- **Auth:** Supabase Auth JWTs, validated by the backend per tenant.
- **Background worker:** `backend/scripts/temporal_hooks_worker.py` (appointment expiry, stale e-way bills).

## 💰 Pricing & Carrier Engines (`POST /api/v1/quotes`)

All rate calculation, volumetric weight, markup, COD fee, and GST (18% SAC 996812) math runs exclusively on the backend (`backend/app/services/pricing/`). Quotes are re-verified on booking (`409 PRICE_CHANGED` if the live quote shifts by more than ₹1.00) and frozen into `payment_details.pricing_breakdown` so later re-weighs (`RepricingService`) stay drift-neutral.

| Service Option | Flow | How It Prices | Configuration & Fallback |
|---|---|---|---|
| **Delhivery Surface** (`DELHIVERY_SURFACE`) & **Delhivery Express** (`DELHIVERY_EXPRESS`) | B2C (Forward & Reverse DTO) | Live HTTP calls to Delhivery Kinko (`GET /api/kinko/v1/invoice/charges/.json`), pincode serviceability (`/c/api/pin-codes/json/`), and TAT (`/api/dc/expected_tat`). Strips Delhivery's `charge_COD` and applies the tenant's own markup (% or flat ₹) + COD policy + 18% GST. | Bound to `DELHIVERY_TENANT_ID` via `DELHIVERY_B2C_TOKEN` (45 calls / 5 min limiter, 30-min 500 g slab cache in `delhivery_price_cache`, 24-h stale cache fallback). `logismart-test` uses `FakeDelhiveryApi`. |
| **Delhivery B2B Cargo** (`DELHIVERY_B2B_SURFACE`) | B2B Cargo (LTL Surface) | Live HTTP calls to Delhivery LTL (`POST /ums/login` → 23-h cached JWT, `POST /freight/estimate`, `/pincode-service`, `/tat/estimate`) using box dimensions (`cm`), total weight (`g`), declared invoice value, and Carrier's vs Owner's Risk (`rov_insurance`). RTO leg is estimated with swapped pins. | Bound to `DELHIVERY_TENANT_ID` via `DELHIVERY_B2B_USERNAME` + `DELHIVERY_B2B_PASSWORD` (90 calls / 5 min limiter, 10-min login back-off on 400/401, 30-min cache + 24-h fallback). `logismart-test` uses `FakeDelhiveryB2BApi`. |
| **Logismart Prime** (`PRIME_SURFACE`) | B2B Cargo (Own-Fleet / Partner Transporters) | Database-backed zone & lane table (`prime_zones`, `prime_zone_pincodes`, `prime_lanes`) seeded from Sheet1 of Logismart's rate card (56 zones, 2,123 pincodes with ODA flags, 74 transporter lanes across 55 routes). Computes chargeable weight (`max(actual, volumetric, min_chargeable_kg)`), base freight (`max(kg × rate, min_lr)`), docket, pickup, odd-weight (> 70 kg box), ODA, optional door-delivery, per-lane or per-option markup (% or flat ₹), and 18% GST. | Self-contained in Postgres (works even when Delhivery is down). Editable in-app at `/[tenant_slug]/settings/prime-lanes` with CSV import/export, or via `scripts/seed_prime_zones.py` and `scripts/import_prime_lanes.py`. |

Staff configure per-option markups (**Percentage `%`** or **Flat `₹`** per shipment) and COD fee policy (`cod_fee_percent` + `cod_fee_min`, fail-closed until both are set) in **Settings → Pricing** (`/[tenant_slug]/settings`). When staff record the carrier's actual AWB/LRN, charged weight, and billed amount on `/ops` or the shipment detail page, `carrier_billing.py` re-bills the seller on the carrier's weight (`MeasurementSource.CARRIER`) and computes pre-GST and incl-GST margin + under-recovery gap flags.

## 📂 Repository structure

- [`.devcontainer/`](.devcontainer/devcontainer.json): GitHub Codespaces / Dev Containers setup (Python 3.11,
  Node 20, Poetry, declared Codespaces secrets, and `post-create.sh`).
- [`.vscode/`](.vscode/tasks.json): shared editor settings, tasks (`Naviera: Run Full Stack`) and debug launch
  configs.
- [`backend/`](backend/README.md): FastAPI app, Alembic migrations, scripts (seed, wipe, worker) and tests.
- [`frontend/`](frontend/README.md): Next.js app and the generated OpenAPI client (`src/api_client`).
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md): fork bootstrap, deploy order, migrations, golden suite, live wipe, and
  go-live checklist.
- [`docs/LOGISMART_HANDOVER_GUIDE.md`](docs/LOGISMART_HANDOVER_GUIDE.md): non-technical staff & operations manual
  mapped to Delhivery One.
- [`docs/BACKLOG.md`](docs/BACKLOG.md): work deferred after the MVP go-live (security hardening, hosting upgrades,
  integrations), each with the reason it waits.

## 🚀 Fork & run in GitHub Codespaces

The repository is self-contained for GitHub Codespaces:

1. **Create a Supabase project** at [supabase.com](https://supabase.com) and copy from **Project Settings**:
   - **Database → Connection string (Transaction pooler, port `6543`)**: replace `postgresql://` with
     `postgresql+asyncpg://` and URL-encode special characters in the password (`$` → `%24`).
   - **API**: `Project URL` (`https://<project-ref>.supabase.co`), `anon public` key, and `JWT Secret`.
2. **Configure Codespaces secrets** (in your fork: **Settings → Secrets and variables → Codespaces**, matching
   the `"secrets"` block in [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json)):
   - Required: `DATABASE_URL`, `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `REVALIDATION_SECRET`.
   - Optional live Delhivery pricing (bound to `DELHIVERY_TENANT_ID`): `DELHIVERY_B2C_TOKEN`, `DELHIVERY_B2C_BASE_URL`, `DELHIVERY_TENANT_ID`, `DELHIVERY_B2B_USERNAME`, `DELHIVERY_B2B_PASSWORD`, `DELHIVERY_B2B_BASE_URL` (leave unset in forks/dev — `logismart-test` uses built-in deterministic fakes).
   - Automatically derived by `post-create.sh` when omitted: `ALEMBIC_DATABASE_URL` (from `DATABASE_URL`),
     `JWT_ISSUER` (`${SUPABASE_URL}/auth/v1`), `NEXT_PUBLIC_SUPABASE_URL` (from `SUPABASE_URL`), and
     `NEXT_PUBLIC_SUPABASE_ANON_KEY` (from `SUPABASE_ANON_KEY`).
   - If you launch the Codespace without setting secrets first, `.devcontainer/post-create.sh` copies
     `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env.local` and prints
     which keys still need values.
3. **Open in GitHub Codespaces** (`Code → Codespaces → Create codespace`). The container installs Python 3.11,
   Node 20, Poetry, `backend/.venv` and `frontend/node_modules`, writes the env files, and adds the
   `run-backend` and `run-frontend` shell aliases.
4. **Apply database migrations** (on your new, empty Supabase database):
   ```bash
   cd backend
   poetry run alembic upgrade head
   ```
5. **Bootstrap your first tenant and Owner account**:
   - **Test/demo workspace (`logismart-test`, recommended for exploring all roles and running the test suite):**
     creates the `logismart-test` tenant, 8 role accounts in `auth.users` + `public."user"` (`owner@`, `admin@`,
     `operations@`, `support@`, `readonly@`, `customerb2c@`, `customerb2b@`, `b2bonboarding@` `logismart.in`),
     3 saved addresses, and ₹0 wallets:
     ```bash
     cd backend
     GOLDEN_TEST_PASSWORD='<choose-a-password>' poetry run python -m scripts.seed_logismart_test --execute
     ```
   - **Default tenants (`naviera` and `logismart`):** see [`docs/RUNBOOK.md` §1.2](docs/RUNBOOK.md#12-bootstrapping-a-fresh-fork-empty-supabase-database)
     for seeding the tenant rows and claiming the first `owner` account via signup (`POST /api/v1/users/auth/signup`).
6. **Start the stack**: run the VS Code task **`Naviera: Run Full Stack`**, or in two terminals:
   - `run-backend` (`cd backend && poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app`)
   - `run-frontend` (`cd frontend && npm run dev`)
   - Optional background worker: `cd backend && poetry run python -m scripts.temporal_hooks_worker`

## 🚢 Production deployment

Render (backend web service + background worker) + Vercel (frontend) + Supabase. Deploy order:
**migrations → backend → worker (same build) → frontend**. Full runbook, rollback notes and go-live checklist:
[`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## 🧪 Testing

| What | Command | Touches the DB? |
|---|---|---|
| Frontend checks | `cd frontend && npx tsc --noEmit && npm run test:audit && npx vitest run` | no |
| Backend lint + collection | `cd backend && poetry run ruff check . && poetry run pytest scripts/tests --collect-only -q` | no |
| Offline migration SQL | `cd backend && poetry run alembic upgrade head --sql` | no |
| Golden suite (API + UI + unit + integrity) | `cd backend && GOLDEN_TEST_PASSWORD=... bash scripts/run_golden.sh` (see [runbook §5](docs/RUNBOOK.md#5-golden-suite)) | yes (`logismart-test` only) |
