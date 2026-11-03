# Naviera — Master AI Agent & Engineering Directives (`.agents/AGENTS.md`)

> **Canonical Specification:** This file (`.agents/AGENTS.md`) is the single source of truth for AI coding agents (Jetski / Gemini, Claude Code, GitHub Copilot, Codex, Cursor) and human engineers working on **Naviera**. Read this document before analyzing the codebase or writing code.
> - **Root Pointer:** [`../AGENTS.md`](../AGENTS.md)
> - **Delhivery One Knowledge Base:** [`knowledge/delhivery-one.md`](knowledge/delhivery-one.md)
> - **Repo-Scoped Agent Skills:** [`skills/delhivery-parity/SKILL.md`](skills/delhivery-parity/SKILL.md) · [`skills/golden-run/SKILL.md`](skills/golden-run/SKILL.md) · [`skills/db-migration/SKILL.md`](skills/db-migration/SKILL.md) · [`skills/ui-e2e/SKILL.md`](skills/ui-e2e/SKILL.md) · [`skills/release-deploy/SKILL.md`](skills/release-deploy/SKILL.md)
> - **Local Workstation Context (Git-Ignored when present):** `.agents/rules/*.md` (workstation/personal rules), `.agents/TASKS.md` (live task tree), `.agents/knowledge_base/delhivery_one/` (local Delhivery help snapshot).

---

## 1. Product North Star: Delhivery One Parity (`one.delhivery.com`)

Naviera is an enterprise multi-tenant 3PL / 4PL logistics SaaS platform built for **Delhivery One parity** (`https://one.delhivery.com`), serving **Logismart** (`logismart.naviera.com`) as its primary production tenant.

- **Parity Mandate:** Every flow, order status, screen, navigation item, field, term, and financial rule—including the **B2C Express** vs. **B2B Heavy Cargo (LTL/FTL)** split, pickup requests (manifests), NDR/RTO exception handling, hub weight discrepancy, COD remittance, GST billing/invoices, and prepaid wallet ledger—must mirror how Delhivery One works, unless an explicit Logismart-specific simplification is documented in [`../docs/client/DELHIVERY_VS_LOGISMART.md`](../docs/client/DELHIVERY_VS_LOGISMART.md).
- **Source of Truth for Delhivery Behavior:**
  1. **Tracked Delhivery Reference:** [`knowledge/delhivery-one.md`](knowledge/delhivery-one.md) and [`skills/delhivery-parity/SKILL.md`](skills/delhivery-parity/SKILL.md) (contains the complete feature-to-route map, B2C/B2B API wire facts, P0 production probe findings, locked pricing decisions, and the 3-step Admin $\leftrightarrow$ Delhivery playbook).
  2. **Official Delhivery Help Center:** Index at `https://help.delhivery.com/llms.txt` and raw markdown articles at `https://help.delhivery.com/docs/<slug>.md` (plus optional local cache in `.agents/knowledge_base/delhivery_one/`).
  3. Cite the Delhivery article `<slug>` for every parity claim in plans and reviews; treat unexplained deviations as defects.

---

## 2. Role, Pedagogy & Approval-First Workflow

### 2.1 Role & Spring Boot Architecture Bridge
Act as Senior Architect, Lead Developer, and Technical Mentor. When introducing FastAPI, SQLModel, or Next.js App Router concepts, map them to their **Java / Spring Boot** equivalents:

| Spring Boot / Java Platform | FastAPI / Next.js 16 Monorepo | Architectural Purpose |
| :--- | :--- | :--- |
| **`@Autowired`** / Dependency Injection | **`Depends(get_session)`**, **`Depends(get_current_active_user)`** | Resolves and injects database sessions or authenticated user contexts. |
| **JPA / Hibernate Entities** | **`SQLModel(table=True)`** (SQLAlchemy + Pydantic) | Declares database table mapping and schema validation. |
| **`@RestController`** / **`@RequestMapping`** | **`router = APIRouter()`** + `@router.get(...)`, `@router.post(...)` | Defines REST API endpoints and routes request payloads. |
| **DTOs (Data Transfer Objects)** | **`SQLModel`** (non-table models in `app/schemas/v1/`) | Encapsulates input/output validation, serialization, and schema boundaries. |
| **Spring Security Filters** | **`get_current_active_user`** in `backend/app/core/dependencies.py` | Verifies Supabase JWT signatures, validates active state, and resolves user context. |
| **`@Enumerated(EnumType.STRING)`** | **`Enum`** (e.g., `class UserRole(str, Enum)`) | Enforces strict database `VARCHAR`/enum storage matching TypeScript enums. |
| **`JpaRepository<Entity, ID>`** | **Repository Pattern** (`backend/app/repositories/*.py`) | Decouples SQLModel/SQLAlchemy queries from business logic and enforces `tenant_id` filtering. |
| **`@Service`** / `@Transactional` | **Service Pattern** (`backend/app/services/*.py`) | Orchestrates atomic multi-table transactions and business rules. |
| **`SecurityContextHolder.getContext()`** | **`TenantProvider`** + **`useTenant()`** | Provides globally cached tenant context and dynamic client path routing. |

### 2.2 Approval-First Incremental Delivery Loop
1. **Analyze Rigorously:** Search across both `backend/` (models, schemas, endpoints, services, repositories, migrations, tests) and `frontend/` (pages, components, validations, hooks) before proposing changes.
2. **Propose Plan & Ask for Approval:** Present a clear implementation and test plan and wait for user approval before coding complex changes.
3. **Database Migration Approval:** Before running any Alembic migration (`alembic revision` or `alembic upgrade`), explain the exact DDL changes, why they are needed, and any pooling/enum impacts, and obtain explicit user approval (see [`skills/db-migration/SKILL.md`](skills/db-migration/SKILL.md)).
4. **Implement Incrementally & Self-Review:** Keep methods modular and fully type-hinted, avoid inline magic numbers, and run automated checks (`bash backend/scripts/run_golden.sh --quick`) after every phase.
5. **Strict Version Control & Scratch Hygiene:**
   - **Humans Own Commits:** `git commit` is reserved for the human developer. Never run `git commit`, `git push`, or destructive git commands unless explicitly instructed by the user.
   - **Scratch Directory:** Place all temporary scripts, logs, patches, and test outputs inside `llm_resources/.agents/` (git-ignored). Never leave scratch files in the repo root, `backend/`, or `frontend/`.

---

## 3. System Architecture: Edge-Dynamic Monolith & Three Zones

A single **Next.js 16 (App Router, React 19, TypeScript)** frontend (`frontend/`) and a single **FastAPI (Python 3.11+, async SQLAlchemy 2.0 + SQLModel)** backend (`backend/`) serve all tenants dynamically without per-client deployments.

### 3.1 Frontend Zone Strategy (`frontend/src/`)
1. **Edge Traffic Controller (`frontend/src/middleware.ts`):** Extracts the tenant slug from subdomain (`<slug>.naviera.com`), custom domain (`CUSTOM_DOMAINS`), or local path (`/logismart/...`) and rewrites internally to `/[tenant_slug]/...`.
2. **Three Zones under `frontend/src/app/[tenant_slug]/`:**
   - **Zone A — `(marketing)/`:** Public landing pages, public rate calculator, legal/compliance pages (Server Components, SEO-optimized).
   - **Zone B — `(app)/`:** Authenticated workspace dashboard, B2C Express (`/dashboard`, `/shipments`, `/pickups`, `/exceptions`, `/wallet`, `/remittances`, `/invoices`, `/weight-mismatch`, `/support`, `/ops`, `/settings`), and B2B Cargo (`/b2b/*`).
   - **Zone C — `track/`:** Public consignee tracking portal (`/track/[id]`) with PII masking (`mask_name`, `mask_phone`, city/state/PIN only) and zero freight price exposure.
3. **Runtime CSS Variable Theming (`ThemeProvider`):**
   - Tenant brand colors (`--primary`, `--secondary`) are injected at runtime from the tenant's database configuration.
   - **Hard Rule:** Never hardcode Tailwind brand colors (e.g., `bg-blue-500`, `text-indigo-600`) for primary/secondary interactive elements; use semantic theme tokens (`bg-primary`, `text-primary`, `border-primary`). Enforced by `frontend/scripts/find-branding-colors.py`.
4. **Incremental B2C & B2B Coexistence:**
   - Never break or regress existing B2C Express flows (`/dashboard`, `/shipments`, `/pickups`, `/address-book`) when extending B2B Heavy Cargo flows under `/b2b/*`.

### 3.2 Domain Entity Mapping (`PickupRequest` vs. `Manifest`)
- **`PickupRequest` (`pickup_requests` table in `backend/app/models/pickups.py`):**
  Despite the historical table name, `PickupRequest` represents an **individual Shipment / Order / AWB / Lorry Receipt (LR)** (one origin address $\rightarrow$ one destination address, package lines, weight, dimensions, declared value, `tracking_id`). Starts in `OPEN` status.
- **`Manifest` (`manifests` table in `backend/app/models/manifests.py`):**
  Represents a **scheduled Fleet Pickup / Truck Run-Sheet (PUR)** at a warehouse (`pickup_address_id`, `scheduled_date`, `time_slot`). Linking `OPEN` shipments to a manifest transitions them immediately from `OPEN` $\rightarrow$ `ASSIGNED`. Also supports **Blind Pickups** (`is_blind_pickup = True`, `total_boxes = N`) when a pickup truck is requested before individual LRs are booked.

### 3.3 Backend Enterprise Layering (`backend/app/`)
All backend code must strictly respect the 3-tier boundary:
- **Controllers (`backend/app/api/v1/endpoints/*.py`):** HTTP routing, dependency injection (`Depends(get_session)`, `Depends(get_current_active_user)`), request/response schema binding, and idempotency guards (`require_idempotency_key`). **Never write raw SQL queries or domain math inside route handlers.**
- **Services (`backend/app/services/*.py`):** Business logic, pricing strategies (`backend/app/services/pricing/`), state transitions, and atomic multi-table orchestration.
- **Repositories (`backend/app/repositories/*.py`):** Database access (DAOs).
  - **Mandatory Multi-Tenant Isolation:** Every repository query **MUST** scope rows by `tenant_id`.
  - **Mandatory Async Eager Loading:** Always use `selectinload(...)` for child relationships to prevent SQLAlchemy async `MissingGreenlet` serialization errors.
  - **Address Snapshotting:** Editing a shipment's address creates a new snapshot `Address` row rather than mutating a saved address book row in place; deleting from the address book uses soft-delete (`is_saved = False`).

### 3.4 Scheduled Jobs (`temporal-hooks.yml` $\rightarrow$ `POST /api/v1/internal/temporal-hooks/run`)
- **What runs:** `run_temporal_hooks_iteration()` (`backend/scripts/temporal_hooks_worker.py`) runs across all tenants to expire overdue delivery appointments and place parcels with stale (> 72h in-transit, value $\ge$ ₹50,000) e-way bills into `EXCEPTION` (`ON_HOLD`). Every pass is idempotent.
- **How it is triggered in production (Free Render plan):** GitHub Actions workflow [`.github/workflows/temporal-hooks.yml`](../.github/workflows/temporal-hooks.yml) runs every 14 minutes (`*/14 * * * *`, plus manual `workflow_dispatch`) and sends `POST /api/v1/internal/temporal-hooks/run` (`backend/app/api/v1/endpoints/internal.py`) to `$NAVIERA_API_URL` (`https://naviera-backend.onrender.com`) with header `X-Cron-Secret: $CRON_SECRET` (verified via `secrets.compare_digest` against `settings.CRON_SECRET`; returns `403` when unset). Calling the API every 14 minutes also keeps the Free Render `naviera-backend` web service warm inside its 15-minute idle sleep window (750 free hours/month covers one 24/7 web service).

---

## 4. Financial, Pricing & Lifecycle Invariants (Non-Negotiable)

### 4.1 Zero Frontend Math (`frontend/scripts/math-check.py`)
- **The frontend is strictly prohibited from computing, estimating, or simulating any pricing, volumetric weight, GST/tax split, freight slab, or COD collectible math.**
- All numbers displayed in the UI must come directly from backend API responses (`/api/v1/pricing/quote`, `payment_details`, `pricing_breakdown`, `collectible_amounts`).
- `npm run test:audit` runs `frontend/scripts/math-check.py` (AST verifier) and `frontend/scripts/find-branding-colors.py`, failing on any violation.

### 4.2 Option A Hybrid Financials & Single Price Writer (`RepricingService`)
- **Decouple Freight Settlement from Commercial Valuation & COD:**
  - Core queryable freight columns live on `payment_details` (`base_freight`, `tax_amount`, `total_logistics_cost`).
  - Core commercial valuation columns (`shipment_value`, `shipment_tax_value`, `shipment_total_value`, `add_shipping_to_cod`) remain separate from carrier freight.
  - Dynamic surcharges, server-only `carrier_cost`, `markup`, and slab details live in `payment_details` / `pricing_breakdown` JSONB columns.
- **Single Price Writer (`backend/app/services/repricing.py`):**
  - `RepricingService.preview()` and `RepricingService.apply()` are the **ONLY** code paths allowed to modify a shipment's price (`payment_details` totals and `pricing_breakdown`) after initial booking.
  - Every post-booking price change (shipment edit, hub measurement re-weigh in `backend/app/services/shipment.py`, weight dispute resolution, or admin price override) **must** go through `RepricingService` so that a `shipment_charge_adjustments` audit row, the exact wallet delta, and the corresponding GST `CREDIT_NOTE` or `DEBIT_NOTE` are recorded atomically.
- **COD / Door Collectible is Backend-Only (`backend/app/services/cod_payout.py`):**
  - The amount collected at the door (`collectible_amounts` / `door_collectible`) is computed exclusively by `cod_payout.py` and frozen once a shipment reaches `COMPLETED` (Delivered).

### 4.3 Wallet Ledger & GST Documents
- **Wallet Ledger (`backend/app/services/wallet.py`, `backend/app/repositories/wallet.py`):**
  - Every balance change uses `WalletRepository.atomic_adjust` with an idempotency key and records an immutable `wallet_transactions` row (`balance_after`).
  - **Customer vs. Company Wallet:** Customer shipments debit/refund the customer's wallet (`user_id = shipment.user_id`). Staff-booked company shipments debit/refund the tenant company wallet (`user_id = None`).
- **GST Document Engine (`backend/app/services/gst_documents.py`):**
  - Automatically issues sequential FY-scoped GST documents (`SAC 996812` Courier / `SAC 996511` Road GTA, 18% GST split into intra-state `9% CGST + 9% SGST` or inter-state `18% IGST`):
    - `TAX_INVOICE` on initial booking debit.
    - `CREDIT_NOTE` on cancellation refund or downward repricing.
    - `DEBIT_NOTE` on upward repricing / hub weight increase.

### 4.4 Single Status Authority (`ShipmentLifecycleMachine`)
- `backend/app/services/shipment_lifecycle.py` (`ShipmentLifecycleMachine`) is the single authority for allowed status transitions, `TERMINAL_STATUSES`, and `RTO_STATUSES`.
- Every status transition must call `ShipmentLifecycleMachine.validate_transition(old_status, new_status)`. An RTO status can never transition to `COMPLETED`, and no shipment can leave a terminal status.
- When linking shipments to a manifest (`backend/app/repositories/manifests.py`), only shipments in `OPEN` status may be selected, and they must immediately transition to `ASSIGNED`.

---

## 5. Code Hygiene, Enums, Imports & Migrations

1. **Strict Enum Comparisons:** Never compare database or Pydantic enum fields (`PickupStatus`, `ShipmentType`, `ServiceFlow`, `ServiceOption`, `UserRole`, `ProductCategory`, etc.) against raw string literals (`== "OPEN"`). Always use the explicit Enum member (`== PickupStatus.OPEN`).
2. **PEP8 Top-of-File Imports:** All Python `import` statements must sit at the top of the file. Never place imports inside functions or in the middle of modules.
3. **Transient Attributes on SQLModel Instances:** Never use `setattr(entity, "field", val)` for non-column runtime attributes on SQLModel instances (raises Pydantic `ValueError`). Use `object.__setattr__(entity, "field", val)`.
4. **Cross-Boundary API Changes & OpenAPI Codegen:** Whenever backend Pydantic schemas in `backend/app/schemas/v1/` change, regenerate `frontend/src/api_client/` and verify `npx tsc --noEmit`:
   ```bash
   cd frontend
   curl -o openapi.json http://localhost:8000/openapi.json
   npx openapi-typescript-codegen --input openapi.json --output ./src/api_client --client axios
   rm openapi.json
   ```
5. **Approval-First Alembic Migrations (`backend/alembic/`):**
   - **Never run `alembic upgrade` or `alembic revision` without explicit human approval.**
   - Alembic autogenerate does not detect PostgreSQL `ENUM` value changes. Write explicit transactional SQL (`ALTER TYPE ... ADD VALUE IF NOT EXISTS` or rename/recreate enum types) inside migration files. See [`skills/db-migration/SKILL.md`](skills/db-migration/SKILL.md).
6. **`backend/.env` Strictly Matches `Settings`:** `pydantic-settings` rejects unknown keys (`extra="forbid"`). Test and CLI variables (`GOLDEN_TENANT_SLUG`, `GOLDEN_TEST_PASSWORD`, `UI_*`, `PROD_*`) must be exported in the shell, never added to `backend/.env`.

---

## 6. DO-NOT-TOUCH Boundaries

1. **Database Connection Pooling (`backend/app/core/db.py`):**
   - Connects through Supabase PgBouncer (`:6543`, transaction mode).
   - Strictly uses `poolclass=NullPool`, `"statement_cache_size": 0`, and `"prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__"`.
   - **DO NOT** alter `db.py` pooling or statement cache parameters without explicit architectural approval.
2. **Edge Subdomain & Custom-Domain Rewriter (`frontend/src/middleware.ts`):**
   - **DO NOT** modify `middleware.ts` routing/rewriting logic without explicit approval.

---

## 7. Local Development Loop & Four-Tier Verification (`logismart-test` Only)

### 7.1 Standard Local Ports & Services
- **FastAPI Backend (`:8000`):** `cd backend && poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- **Next.js Frontend (`:3000`):** `cd frontend && npm run dev`
- **Headless Chrome CDP (`:9224`):** Used by automated Selenium / CDP UI verification (`backend/scripts/tests/ui_golden/`). Never kill running dev servers (`:8000`, `:3000`) when starting test runs.

### 7.2 Live-Tenant Safety & Seeded Test Personas
- All tests, seeds, and resets are **hard-locked** to the **`logismart-test`** tenant (`ALLOWED_TEST_SLUGS = frozenset({"logismart-test"})` in `backend/scripts/tenant_data_core.py`).
- **Live-Tenant Snapshot Guard:** `run_golden.sh` captures `snapshot_other_tenants()` before and `assert_live_tenants_untouched()` after every DB-touching run (`backend/scripts/golden_checks.py`). Any mutation to live `logismart` or `naviera` rows aborts immediately.
- **Single Concurrency Rule:** Run only **one** DB-touching test session at a time against the shared database.
- **Seeded Test Personas (`logismart-test` only; password in `$GOLDEN_TEST_PASSWORD`):** `owner@logismart.in`, `admin@logismart.in`, `operations@logismart.in`, `support@logismart.in`, `readonly@logismart.in`, `customerb2c@logismart.in`, `customerb2b@logismart.in`, `b2bonboarding@logismart.in`. Never sign in with test accounts on live `/logismart`.

### 7.3 Three-Mode Verification Suite (`backend/scripts/run_golden.sh`)

| Tier | Command | Scope & When to Run |
| :--- | :--- | :--- |
| **1. Quick (`--quick`)** | `bash backend/scripts/run_golden.sh --quick` | **No DB required (~60s).** Runs `ruff check .`, `npx tsc --noEmit`, `npm run test:audit` (`math-check.py` + `find-branding-colors.py`), `vitest`, and 35 pure backend unit test suites (`PURE_UNIT_SUITES`). Run on every code edit. |
| **2. Smoke (`--smoke`)** | `bash backend/scripts/run_golden.sh --smoke` | Resets `logismart-test`, runs `SMOKE_API_SUITES` (B2C lifecycle, B2B lifecycle, pricing matrix) + `SMOKE_UI_SUITES` + `golden_checks.py` invariants + live-count guard (~3–4 min). |
| **3. Full (Default)** | `bash backend/scripts/run_golden.sh` | Runs static + all pure/DB unit suites + all 8 `golden_journeys/` API suites + all headless Chrome `ui_golden/` suites + `golden_checks.py` (~10–12 min). |

See [`skills/golden-run/SKILL.md`](skills/golden-run/SKILL.md) and [`skills/ui-e2e/SKILL.md`](skills/ui-e2e/SKILL.md) for detailed test execution playbooks.

---

## 8. Git & Release Workflow (`dev` $\rightarrow$ PR $\rightarrow$ `master`)

1. **Branch Model:**
   - All day-to-day feature and bugfix work happens on `dev` (or a short-lived feature branch off `dev`), synced to GitHub.
   - `master` is the production branch; pushing or squash-merging a PR into `master` triggers automatic production deployments on **Render** (FastAPI API + background worker) and **Vercel** (Next.js frontend), verified via the post-deploy health & quote checks in [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md).
2. **Post-Squash-Merge `dev` Alignment (Mandatory):**
   - After squash-merging `dev` into `master` on GitHub, immediately realign `dev` with `origin/master` so the next PR has zero merge conflicts:
     - **Option A (Clean Reset — Preferred when `dev` has no unmerged work):**
       ```bash
       git fetch origin
       git checkout dev
       git reset --hard origin/master
       git push --force-with-lease origin dev
       ```
     - **Option B (Ours Merge — If preserving `dev` commit graph):**
       ```bash
       git fetch origin
       git checkout dev
       git merge -s ours origin/master -m "chore: record master squash-merge"
       git push origin dev
       ```
3. **Human Commit Ownership:**
   - `git commit` and `git push` are owned by the human developer unless the user explicitly instructs the agent to stage, commit, or push.

---

## 9. Documentation Map

- **Documentation Index:** [`../docs/README.md`](../docs/README.md)
- **Developer Setup & Testing Guide:** [`../docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md)
- **System Architecture & Pricing Engine:** [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
- **Production Operations & Release Runbook:** [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md)
- **Deferred Work & Backlog:** [`../docs/BACKLOG.md`](../docs/BACKLOG.md)
- **Client Handover Guide (Logismart Team):** [`../docs/client/LOGISMART_HANDOVER_GUIDE.md`](../docs/client/LOGISMART_HANDOVER_GUIDE.md)
- **Delhivery One vs. Logismart Guide:** [`../docs/client/DELHIVERY_VS_LOGISMART.md`](../docs/client/DELHIVERY_VS_LOGISMART.md)
