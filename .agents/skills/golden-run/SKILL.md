---
name: golden-run
description: Runs Naviera's 3-mode verification suite (--quick static+unit, --smoke API+UI+DB, and full pre-merge gate) via backend/scripts/run_golden.sh and inspects structured artifacts.
---

# Golden Verification Suite Skill (`golden-run`)

Use this skill whenever you need to verify backend or frontend code changes, run static compliance audits (`npm run test:audit`), execute pure unit tests, or run the golden API + UI regression suite on `logismart-test`.

## 1. Safety Rules (Mandatory)

1. **`logismart-test` Only:** Every DB-touching test, seed, and reset is hard-locked to `GOLDEN_TENANT_SLUG=logismart-test` (`ALLOWED_TEST_SLUGS` in `backend/scripts/tenant_data_core.py`). Never point tests at live `logismart` or `naviera`.
2. **One DB Session at a Time:** Only run **one** DB-touching mode (`--smoke` or `full`) at a time against the shared Supabase Postgres instance.
3. **Live-Tenant Count Guard:** `run_golden.sh` automatically runs `python -m scripts.golden_checks live-counts --tenant logismart` before (`live_before.json`) and `compare-counts` after (`live_after.json`) every DB run (`backend/scripts/golden_checks.py`). If any row count on live `logismart` changes, the `live` phase fails immediately.

---

## 2. Choosing the Right Verification Mode (`backend/scripts/run_golden.sh`)

### Mode 1: `--quick` (Static Audits + Pure Unit Tests — No DB / No Servers Required, ~60s)
Run `--quick` after every backend or frontend edit:
```bash
bash backend/scripts/run_golden.sh --quick
```
What `--quick` executes (`PHASES=(static unit)`):
1. **Backend Ruff Lint:** `poetry run ruff check .`
2. **Frontend TypeScript Check:** `npx tsc --noEmit`
3. **Frontend Architectural Audit (`npm run test:audit`):**
   - `frontend/scripts/math-check.py` (AST check: fails with exit code `1` if any frontend file computes pricing, volumetric weight, GST, or COD math).
   - `frontend/scripts/find-branding-colors.py` (fails with exit code `1` if any component uses hardcoded Tailwind brand colors instead of runtime `--primary` / `--secondary` CSS variables).
4. **Frontend Vitest Unit Suite:** `npx vitest run` (64 component and validation test suites).
5. **Backend Pure Unit Suites (`PURE_UNIT_SUITES`):** 35 fast `pytest` suites (`test_money.py`, `test_pricing_quotes_unit.py`, `test_prime_pricing_unit.py`, `test_booking_pricing_unit.py`, `test_delhivery_b2b_unit.py`, `test_repricing_unit.py`, `test_repricing_redesign_unit.py`, `test_gst_documents_unit.py`, `test_shipment_lifecycle.py`, `test_ndr_stage_rules.py`, `test_platform_guards_unit.py`, `test_temporal_hooks_worker.py`, etc.).

### Mode 2: `--smoke` (Money API Suites + Money UI Journey + Pure Unit + Integrity + Live Guard)
Run `--smoke` when modifying API endpoints, services, repositories, pricing, or wallet/GST flows (requires backend `:8000` and frontend `:3000` running):
```bash
export GOLDEN_TEST_PASSWORD="<test-account-password>"
bash backend/scripts/run_golden.sh --smoke
```
What `--smoke` executes (`PHASES=(static preflight api ui unit integrity live)`):
1. **`static`:** Runs all static checks (`ruff`, `tsc --noEmit`, `npm run test:audit`, `vitest`).
2. **`preflight`:** Verifies `:8000` and `:3000` are up, checks Chrome CDP `:9224` (or falls back to self-launched headless Chrome), and snapshots `live_before.json`.
3. **`api` (`SMOKE_API_SUITES`):**
   - `scripts/tests/golden_journeys/test_suite_9_repricing.py`
   - `scripts/tests/golden_journeys/test_suite_10_crosscut.py`
   - `scripts/tests/golden_journeys/test_suite_11_lifecycle.py`
4. **`ui` (`SMOKE_UI_SUITES`):** `scripts/tests/ui_golden/test_ui_helpers.py` and `scripts/tests/ui_golden/test_ui_money.py` (skip with `GOLDEN_SKIP_UI=1` when running API-only checks).
5. **`unit`:** Runs all 35 `PURE_UNIT_SUITES`.
6. **`integrity` & `live`:** Runs `python -m scripts.golden_checks integrity --tenant logismart-test` and asserts `live_before.json == live_after.json`.

### Mode 3: `full` (Default Pre-Merge Gate: All 8 Golden API Suites + All UI Golden Suites + Full Unit)
Run `full` (no flag) before merging `dev` into `master`:
```bash
export GOLDEN_TEST_PASSWORD="<test-account-password>"
bash backend/scripts/run_golden.sh
```
Runs all 8 ordered `FULL_API_SUITES` (`test_suite_1_2_auth_settings_rates.py` through `test_suite_13_notes_lite.py`), the complete `scripts/tests/ui_golden` directory, `FULL_UNIT_SUITES` (44 total: 35 pure + 9 DB savepoint suites), `integrity`, and `live`.

---

## 3. Reading Artifacts & Debugging Failures

Every run writes logs and JUnit XML to `llm_resources/.agents/golden_runs/artifacts/<UTC-timestamp>/`:
- `static_ruff.log`, `static_tsc.log`, `static_test_audit.log`, `static_vitest.log`
- `api.xml`, `ui.xml`, `unit.xml` (summarized via `poetry run python -m scripts.golden_checks junit-summary`)
- `live_before.json` & `live_after.json`
