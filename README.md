# Naviera — Multi-Tenant B2C & B2B 3PL Logistics Platform

**Naviera** is an enterprise multi-tenant 3PL / 4PL logistics SaaS platform built for **Delhivery One (`one.delhivery.com`) parity**, powering **Logismart** (`https://logismart.naviera.com`) across **B2C Express Parcels** and **B2B Heavy Cargo (LTL/FTL)**.

---

## 1. Core Capabilities

- **Edge-Dynamic Multi-Tenant Monolith:** Single **Next.js 16 (App Router, React 19, TypeScript)** frontend and single **FastAPI (Python 3.11+, async SQLAlchemy 2.0 + SQLModel)** backend serving custom tenant subdomains (`<slug>.naviera.com`) with runtime CSS variable theming (`--primary`, `--secondary`).
- **Dual Service Flows (`B2C Express` & `B2B Cargo`):**
  - **B2C Express:** 3-click parcel booking, live **Delhivery Surface** & **Delhivery Express** rate cards, `4×6` thermal AWB labels, pickup scheduling, and NDR/RTO management.
  - **B2B Heavy Cargo:** Multi-box Lorry Receipt (LR) booking, **Door Delivery** vs. **Godown / Hub Self-Pickup** (`₹0` door fee), side-by-side **Logismart Prime** (Delhi-NCR 18-zone matrix) vs. **Delhivery B2B Cargo** rates, and 3-copy A4 LR dockets + box stickers.
- **Enterprise Financial & GST Engine:**
  - **Zero Frontend Math:** All volumetric weight, freight slab, markup, GST (`SAC 996812` / `SAC 996511`, `9% CGST + 9% SGST` or `18% IGST`), and COD door-collectible calculations execute strictly on the backend.
  - **Single Price Writer (`RepricingService`):** Every post-booking weight scan, shipment edit, weight dispute resolution, or admin price override atomically updates the prepaid wallet ledger, records a `shipment_charge_adjustments` audit row, and issues a sequential GST **Credit Note** or **Debit Note** linked to the original **Tax Invoice**.

---

## 2. Quick Start (Local Workstation or GitHub Codespaces)

```bash
# 1. Copy environment templates (if missing) & install dependencies
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env.local
cd backend && poetry install --with e2e && cd ..
cd frontend && npm ci && cd ..

# 2. Start Backend (:8000) & Frontend (:3000) (or run VS Code task "Naviera: Run Full Stack")
cd backend && poetry run uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000
cd frontend && npm run dev -- -p 3000
```
Open `http://localhost:3000/logismart-test` (Frontend) and `http://localhost:8000/docs` (Swagger UI). *(Also includes a lean `.devcontainer/` with Python 3.11 + Node 20 where `post-create.sh` runs `poetry install --with e2e` + `npm ci` and copies missing `.env` templates while Codespaces secrets arrive as environment variables; see [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).)*

---

## 3. Verification Tiers (`backend/scripts/run_golden.sh`)

All DB-touching tests and seeds are hard-locked to the isolated **`logismart-test`** tenant and guarded by a before/after live-tenant row-count snapshot (`backend/scripts/golden_checks.py`):

```bash
# Mode 1 — Quick (~60s, no DB): ruff + tsc + test:audit + vitest + 35 pure unit suites
bash backend/scripts/run_golden.sh --quick

# Mode 2 — Smoke (~3–4m): reset logismart-test + core B2C/B2B/Pricing API & UI journeys + golden_checks
bash backend/scripts/run_golden.sh --smoke

# Mode 3 — Full (default, ~10–12m): static + unit + all 8 golden API suites + headless Chrome UI E2E (:9224)
bash backend/scripts/run_golden.sh
```

---

## 4. Documentation & AI Agent Guides

| Audience | Document | Description |
| :--- | :--- | :--- |
| **All Readers** | **[`docs/README.md`](docs/README.md)** | Complete documentation index by audience |
| **AI Coding Agents** | **[`.agents/AGENTS.md`](.agents/AGENTS.md)** · **[`AGENTS.md`](AGENTS.md)** · **[`delhivery-one.md`](.agents/knowledge/delhivery-one.md)** | Canonical architectural directives, Delhivery One knowledge base, layering & money rules, DO-NOT-TOUCH files, testing & git workflow |
| **Agent Skills** | **[`delhivery-parity`](.agents/skills/delhivery-parity/SKILL.md)** · **[`golden-run`](.agents/skills/golden-run/SKILL.md)** · **[`db-migration`](.agents/skills/db-migration/SKILL.md)** · **[`ui-e2e`](.agents/skills/ui-e2e/SKILL.md)** · **[`release-deploy`](.agents/skills/release-deploy/SKILL.md)** | Repo-scoped operational playbooks for AI agents |
| **Developers** | **[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)** · **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** | Local/Codespaces setup, system diagrams, pricing engine & money flows |
| **DevOps / SRE** | **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)** · **[`docs/BACKLOG.md`](docs/BACKLOG.md)** | Production environment variables, go-live checklist, rollback & backlog |
| **Client Team** | **[`docs/client/LOGISMART_HANDOVER_GUIDE.md`](docs/client/LOGISMART_HANDOVER_GUIDE.md)** · **[`docs/client/DELHIVERY_VS_LOGISMART.md`](docs/client/DELHIVERY_VS_LOGISMART.md)** | Step-by-step business handover manual, Delhivery One comparison & [51-screen visual gallery](docs/client/images/INDEX.md) |

---

## 5. Production Deployment Targets & Key Environment Variables

- **Branch Flow:** Feature work on `dev` $\rightarrow$ Pull Request $\rightarrow$ Squash-Merge to `master` (then reset/sync `dev` to `origin/master`).
- **Frontend (Vercel):** Deployed automatically from `master` to `https://naviera.com`, `https://logismart.naviera.com`, and custom domains configured in `CUSTOM_DOMAIN_TENANTS` (`logismart.in:logismart,www.logismart.in:logismart`).
- **Backend API & Scheduled Temporal Hooks (Render + GitHub Actions):** Deployed automatically from `master` to `https://naviera-backend.onrender.com` (`naviera-backend`, `uvicorn app.main:app`). Scheduled job [`.github/workflows/temporal-hooks.yml`](.github/workflows/temporal-hooks.yml) runs every 14 minutes (`*/14 * * * *`) against `POST /api/v1/internal/temporal-hooks/run` (authenticated via `X-Cron-Secret: $CRON_SECRET`) to execute `run_temporal_hooks_iteration()` and keep the Free Render service warm.
- **Database & Auth (Supabase):** Managed PostgreSQL (via PgBouncer transaction pooler `:6543`) and Supabase Auth.

| Target | Key Environment Variables / Secrets |
| :--- | :--- |
| **Backend (`backend/.env` / Render `naviera-backend`)** | `ENVIRONMENT`, `DATABASE_URL` (`:6543`), `ALEMBIC_DATABASE_URL` (`:5432`), `SUPABASE_URL`, `SECRET_KEY`, `SUPABASE_SERVICE_KEY`, `BACKEND_CORS_ORIGINS`, `FRONTEND_APP_URL`, `REVALIDATION_SECRET`, `CRON_SECRET`, `DELHIVERY_B2C_TOKEN`, `DELHIVERY_TENANT_ID`, `DELHIVERY_LIVE_TENANT_SLUGS` |
| **Frontend (`frontend/.env.local` / Vercel)** | `BACKEND_API_URL`, `NEXT_PUBLIC_ROOT_DOMAIN`, `CUSTOM_DOMAIN_TENANTS`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `REVALIDATION_SECRET` |
| **GitHub Actions (`.github/workflows/temporal-hooks.yml`)** | `CRON_SECRET` (matches Render `CRON_SECRET`), `NAVIERA_API_URL` (`https://naviera-backend.onrender.com`) |
