# Naviera — AI Coding Agent Entrypoint (`AGENTS.md`)

> **Canonical Blueprint:** The complete, authoritative engineering specification and workspace rules live in **[`.agents/AGENTS.md`](.agents/AGENTS.md)** (auto-loaded by Jetski and tracked in this repository). Every AI coding agent (Jetski / Gemini, Claude Code, GitHub Copilot, Codex, Cursor) **must read [`.agents/AGENTS.md`](.agents/AGENTS.md)** and **[`.agents/knowledge/delhivery-one.md`](.agents/knowledge/delhivery-one.md)** before modifying any code.

---

## Quick Summary for AI Agents

1. **Product North Star — Delhivery One Parity (`one.delhivery.com`):**
   Every flow, status, field, and financial rule across **B2C Express** and **B2B Heavy Cargo (LTL/FTL)** mirrors Delhivery One (`https://help.delhivery.com/llms.txt`), except where explicitly documented in [`docs/client/DELHIVERY_VS_LOGISMART.md`](docs/client/DELHIVERY_VS_LOGISMART.md). Full feature map & Delhivery API wire facts live in **[`.agents/knowledge/delhivery-one.md`](.agents/knowledge/delhivery-one.md)**.
2. **Architecture — Edge-Dynamic Monolith:**
   - **Frontend (`frontend/`):** Next.js 16 (App Router, React 19, TypeScript) with Three Zones under `frontend/src/app/[tenant_slug]/`: `(marketing)`, `(app)`, and `track`. Runtime CSS variables (`--primary`, `--secondary`) are injected per tenant—never hardcode Tailwind brand colors (`bg-blue-500`).
   - **Backend (`backend/`):** FastAPI + SQLModel (async SQLAlchemy 2.0) strictly layered into `endpoints/` $\rightarrow$ `services/` $\rightarrow$ `repositories/`. Every repository query **must** filter by `tenant_id` and use `selectinload(...)`.
3. **Money & Lifecycle Rules (Non-Negotiable):**
   - **Zero Frontend Math:** All rate, volumetric, GST, and COD calculations happen strictly on the backend (`npm run test:audit` enforces `frontend/scripts/math-check.py` and `frontend/scripts/find-branding-colors.py`).
   - **Single Price Writer:** Only `RepricingService` (`backend/app/services/repricing.py`) may modify a shipment's price after booking (atomically recording a `shipment_charge_adjustments` row, wallet delta, and GST `CREDIT_NOTE` / `DEBIT_NOTE`).
   - **Single Status Authority:** Only `ShipmentLifecycleMachine` (`backend/app/services/shipment_lifecycle.py`) governs status transitions.
4. **DO-NOT-TOUCH Files:**
   - `backend/app/core/db.py` (PgBouncer `:6543` `NullPool` + statement cache disabled).
   - `frontend/src/middleware.ts` (Edge subdomain and custom-domain router).
   - Never run `alembic revision` or `alembic upgrade` without explicit human approval.
5. **Local Dev Loop & Testing Modes (`logismart-test` Only):**
   - Servers: FastAPI on `:8000`, Next.js on `:3000`, headless Chrome CDP on `:9224`.
   - `bash backend/scripts/run_golden.sh --quick` — Static checks (`ruff`, `tsc --noEmit`, `npm run test:audit`), `vitest`, and 35 pure unit suites (no DB, ~60s).
   - `bash backend/scripts/run_golden.sh --smoke` — Resets `logismart-test`, runs core API + UI journeys + `golden_checks.py` + live-tenant snapshot guard.
   - `bash backend/scripts/run_golden.sh` — Full pre-merge gate (all API journeys + headless Chrome `ui_golden/`).
6. **Git & Release Flow:**
   - Feature work on `dev` $\rightarrow$ PR $\rightarrow$ squash-merge to `master` $\rightarrow$ auto-deploys **Render** + **Vercel**. After each squash-merge, realign `dev` to `origin/master` (`git reset --hard origin/master && git push --force-with-lease origin dev` or `git merge -s ours origin/master`).
   - Humans own `git commit` and `git push`. Scratch files belong strictly in `llm_resources/.agents/` (git-ignored).

---

## Repo-Scoped Agent Knowledge & Skills (`.agents/`)

| Resource | File | When to Load |
| :--- | :--- | :--- |
| **Delhivery Knowledge** | [`.agents/knowledge/delhivery-one.md`](.agents/knowledge/delhivery-one.md) | Reference for Delhivery One feature map, B2C/B2B API wire facts, pricing rules, and 3-step ops playbook. |
| **`delhivery-parity`** | [`.agents/skills/delhivery-parity/SKILL.md`](.agents/skills/delhivery-parity/SKILL.md) | Planning, implementing, or reviewing any feature for Delhivery One parity and citing help-center slugs. |
| **`golden-run`** | [`.agents/skills/golden-run/SKILL.md`](.agents/skills/golden-run/SKILL.md) | Running `--quick`, `--smoke`, or default `full` verification and inspecting `summary.json`. |
| **`db-migration`** | [`.agents/skills/db-migration/SKILL.md`](.agents/skills/db-migration/SKILL.md) | Authoring or applying Alembic migrations (including raw SQL PostgreSQL `ENUM` changes). |
| **`ui-e2e`** | [`.agents/skills/ui-e2e/SKILL.md`](.agents/skills/ui-e2e/SKILL.md) | Running or writing headless Chrome Selenium/CDP `:9224` E2E tests (`backend/scripts/tests/ui_golden/`). |
| **`release-deploy`** | [`.agents/skills/release-deploy/SKILL.md`](.agents/skills/release-deploy/SKILL.md) | Promoting `dev` $\rightarrow$ `master`, checking Render/Vercel env vars, post-deploy verification, or rolling back. |

---

## Documentation Links

- **[Canonical Agent Directives (`.agents/AGENTS.md`)](.agents/AGENTS.md)**
- **[Delhivery One Knowledge Base (`.agents/knowledge/delhivery-one.md`)](.agents/knowledge/delhivery-one.md)**
- **[Documentation Hub (`docs/README.md`)](docs/README.md)**
- **[Developer Setup & Workflow (`docs/DEVELOPMENT.md`)](docs/DEVELOPMENT.md)**
- **[System Architecture & Pricing Engine (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)**
- **[Operations & Deployment Runbook (`docs/RUNBOOK.md`)](docs/RUNBOOK.md)**
- **[Deferred Work & Backlog (`docs/BACKLOG.md`)](docs/BACKLOG.md)**
