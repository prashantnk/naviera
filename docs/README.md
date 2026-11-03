# Naviera Documentation Hub (`docs/README.md`)

Welcome to the documentation hub for **Naviera**—the multi-tenant 3PL / 4PL logistics SaaS platform powering **Logismart** (`https://logismart.naviera.com`) with **Delhivery One parity** (`https://one.delhivery.com`).

Choose the guide below that matches your role:

---

## 1. By Audience

### 🤖 AI Coding Agents (Jetski / Gemini, Claude Code, Copilot, Codex, Cursor)
- **[`.agents/AGENTS.md`](../.agents/AGENTS.md)** *(Canonical)* & **[`AGENTS.md`](../AGENTS.md)** *(Root Pointer)* — Master system directives, Delhivery One parity mandate, Three-Zone Edge-Dynamic Monolith rules, Controller/Service/Repository segregation, money/repricing/lifecycle invariants, DO-NOT-TOUCH files, testing tiers, and Git workflow.
- **[`.agents/knowledge/delhivery-one.md`](../.agents/knowledge/delhivery-one.md)** — Persistent Delhivery One integration knowledge base (feature-to-route map, B2C & B2B API wire facts, P0 production probe findings, locked pricing decisions, and the 3-step Admin $\leftrightarrow$ Delhivery playbook).
- **Repo-Scoped Agent Skills (`.agents/skills/`):**
  - **[`delhivery-parity`](../.agents/skills/delhivery-parity/SKILL.md)** — Enforces Delhivery One product and API parity and help-center slug citations.
  - **[`golden-run`](../.agents/skills/golden-run/SKILL.md)** — How to run `backend/scripts/run_golden.sh` (`--quick`, `--smoke`, and default `full`) and inspect structured artifacts.
  - **[`db-migration`](../.agents/skills/db-migration/SKILL.md)** — Approval-first Alembic migrations and raw SQL handling for PostgreSQL `ENUM` mutations.
  - **[`ui-e2e`](../.agents/skills/ui-e2e/SKILL.md)** — Headless Chrome (CDP `:9224` / Selenium) E2E journeys (`backend/scripts/tests/ui_golden/`), `DbOracle` money parity, and DOM card-containment checks.
  - **[`release-deploy`](../.agents/skills/release-deploy/SKILL.md)** — `dev` $\rightarrow$ PR $\rightarrow$ `master` release flow, Render + Vercel env configuration, post-deploy verification, and rollback procedures.

### 💻 Software Engineers & Contributors
- **[`DEVELOPMENT.md`](DEVELOPMENT.md)** — Local workstation setup (primary) & GitHub Codespaces setup, `.env` templates, running backend (`:8000`) & frontend (`:3000`), the 4-tier verification suite, OpenAPI client codegen, and Git workflow.
- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — High-level system diagrams, Edge-Dynamic Monolith routing, pricing engine architecture (Delhivery B2C, Delhivery B2B with `B2CFallbackDelhiveryB2BApi`, Logismart Prime), Option A Hybrid Financials, `RepricingService`, and `ShipmentLifecycleMachine`.
- **[`BACKLOG.md`](BACKLOG.md)** — Prioritized post-MVP engineering backlog and external credential items.

### 🛠️ DevOps, SRE & Platform Operators
- **[`RUNBOOK.md`](RUNBOOK.md)** — Production deployment checklist (Supabase, Render API + background worker, Vercel), environment variable reference, tenant data seeding/wiping (`logismart-test` vs. live `logismart`), Delhivery rate-cache operations, and rollback playbook.

### 📦 Client & Business Operations Team (Logismart Staff & Customers)
- **[`client/LOGISMART_HANDOVER_GUIDE.md`](client/LOGISMART_HANDOVER_GUIDE.md)** — Complete, zero-jargon day-to-day operational manual for Logismart Owners, Admins, Operations/Hub Staff, Support, Read-Only Auditors, and B2C/B2B Customers, with step-by-step screenshots.
- **[`client/DELHIVERY_VS_LOGISMART.md`](client/DELHIVERY_VS_LOGISMART.md)** — Side-by-side comparison of `one.delhivery.com` vs. Logismart workflows, simplifications, and 3-click booking flows.
- **[`client/images/INDEX.md`](client/images/INDEX.md)** — Organized visual gallery index of all 51 application screenshots across 12 functional flows (`public`, `dashboard`, `settings`, `team`, `booking`, `orders`, `pickups`, `ops`, `exceptions`, `finance`, `support`, `roles`).

---

## 2. Directory Layout

```plaintext
docs/
├── README.md                              # This index (by audience)
├── DEVELOPMENT.md                         # Setup, running, testing, codegen, git & release flow
├── ARCHITECTURE.md                        # System diagrams, modules, pricing engine & money flows
├── RUNBOOK.md                             # Production ops, env vars, deploy, smoke_prod & rollback
├── BACKLOG.md                             # Deferred post-MVP work & external dependencies
└── client/
    ├── LOGISMART_HANDOVER_GUIDE.md        # Client-facing operational handbook
    ├── DELHIVERY_VS_LOGISMART.md          # Delhivery One vs. Logismart comparison guide
    └── images/
        ├── INDEX.md                       # Visual screenshot catalog by flow
        ├── public/                        # Landing page, public tracking, login (01–03)
        ├── dashboard/                     # B2C & B2B dashboards, flow switcher (04–06)
        ├── settings/                      # Company profile, branding, UPI, pricing, Prime lanes (07–12)
        ├── team/                          # Team directory & staff/customer editors (13–15)
        ├── booking/                       # B2C & B2B booking wizards & rate calculator (04c, 16–18)
        ├── orders/                        # Orders list, shipment detail, carrier & hub override (19–20g)
        ├── pickups/                       # Pickup requests / manifests (21–22)
        ├── ops/                           # Ops Control Tower desktop & mobile rider view (23–24)
        ├── exceptions/                    # B2C & B2B NDR / delivery exceptions (25–26)
        ├── finance/                       # Wallet, recharges, COD remittances, GST invoices, weight disputes (27–32)
        ├── support/                       # Support ticket queue & raise-ticket dialog (33–33b)
        └── roles/                         # Read-only, B2C/B2B customer dashboards & B2B access (34–38)
```
