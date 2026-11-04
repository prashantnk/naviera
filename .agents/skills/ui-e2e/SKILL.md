---
name: ui-e2e
description: Runs and extends headless Chrome (CDP :9224 / Playwright / Selenium) E2E journeys, DB-to-UI money parity assertions, and DOM child-vs-card overflow checks on the logismart-test tenant.
---

# UI End-to-End Verification Skill (`ui-e2e`)

Use this skill when running or authoring browser E2E tests in `backend/scripts/tests/ui_golden/`, driving Chrome on CDP `:9224`, verifying visual layout and DOM child-vs-card bounding-box containment, or checking DB-to-UI financial parity via `DbOracle`.

> **Agent Test Catalog ("Changed X → Rerun Y"):** See [`../../knowledge/test-catalog.md`](../../knowledge/test-catalog.md) for the complete 31-screen × 9-persona route matrix (`S01–S31`), flow coverage registry, and verification history.

## 1. Architecture of `backend/scripts/tests/ui_golden/`

The UI golden suite drives Chrome (attached over CDP `127.0.0.1:9224` or self-launched headless Chrome) against the live Next.js (`:3000`) and FastAPI (`:8000`) servers on the **`logismart-test`** tenant only:

- **`ui_config.py`:** Enforces `UI_TENANT_SLUG == "logismart-test"` (refuses to run against `logismart` or `naviera`). Configures `UI_FRONTEND_URL` (default `http://localhost:3000`), `UI_API_URL` (default `http://localhost:8000`), and `UI_CDP_URL` (`http://127.0.0.1:9224`).
- **`auth.py`:** Signs in once per role via `POST /api/v1/users/auth/login` and writes storage state so role switches take `<1s` without repeated login form submissions.
- **`db_oracle.py` (`DbOracle`):** Queries the Postgres database (`NullPool`) directly to assert that every rupee figure rendered in the DOM matches `payment_details.total_logistics_cost`, `wallet.balance`, `billing_invoices`, and `shipment_charge_adjustments` to 2 decimal places (`money.py`).
- **`network_guard.py`:** Inspects browser network/console events and fails any test if an `/api/v1/*` request returns `HTTP >= 500` or if an uncaught browser error occurs.
- **`pages/base_page.py` (`assert_no_horizontal_overflow` & Card Containment):**
  - Runs at Desktop (`1440x900`), Laptop (`1280x800`), and Mobile (`390x844`, for `/track/*` and `/ops`) viewports to ensure `document.documentElement.scrollWidth <= clientWidth + 2`.
  - Also enforce **child-vs-card bounding-box containment**: every visible `<input>`, `<textarea>`, `<select>`, `<button>`, `[role="combobox"]`, and `[data-slot="input"]` inside a card/dialog (`[data-slot="card"]`, `[role="dialog"]`, `.border`) must satisfy `childRect.right <= ancestorRect.right + 2` and `childRect.left >= ancestorRect.left - 2` (always use `w-full min-w-0` on form controls and grid items).
- **`pdf.py`:** Downloads generated PDFs (A4 3-copy Lorry Receipt dockets, `4x6` thermal labels, GST Tax Invoices / Credit Notes / Debit Notes) and extracts text via `pypdf` to verify AWB/LR numbers, SAC codes, and tax totals.

---

## 2. Prerequisites

1. **Optional `e2e` Poetry Group Installed:**
   - `.devcontainer/post-create.sh` installs only `main + dev` (`poetry install`) to keep Codespaces fast. Before running `ui_golden/` suites, ensure the `e2e` group (`pytest-playwright`, `pypdf`) is installed:
     ```bash
     cd backend && poetry install --with e2e
     ```
2. **Backend & Frontend Servers Running (Do Not Kill Existing Dev Servers):**
   - Backend listening on `http://localhost:8000` (`poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app`)
   - Frontend listening on `http://localhost:3000` (`npm run dev`)
   - Optional shared Chrome with remote debugging on `127.0.0.1:9224` (if not running, `browser_session.py` launches its own headless Chrome automatically).
3. **Test Tenant Seeded (`logismart-test`):**
   ```bash
   cd backend
   export GOLDEN_TEST_PASSWORD="<test-account-password>"
   poetry run python -m scripts.seed_logismart_test --execute
   ```

---

## 3. Running the UI Golden Suites

### Run All UI Golden Suites
```bash
cd backend
export GOLDEN_TEST_PASSWORD="<test-account-password>"
poetry run pytest scripts/tests/ui_golden -m ui -v -p no:cacheprovider
```

### Run Individual UI Suites
- **Pure Helper Unit Tests (No Browser / No DB — <1s):**
  ```bash
  poetry run pytest scripts/tests/ui_golden/test_ui_helpers.py -v
  ```
- **Smoke Journeys (Public Home, Rate Calculator, Login, B2C & B2B Booking, Public Tracking, Ops):**
  ```bash
  poetry run pytest scripts/tests/ui_golden/test_ui_smoke.py -v -p no:cacheprovider
  ```
- **Money, Wallet, GST Invoices, Remittances & Weight Dispute Parity:**
  ```bash
  poetry run pytest scripts/tests/ui_golden/test_ui_money.py -v -p no:cacheprovider
  ```
- **D9 Pricing Matrix, Bidirectional Override & Hub Measurement Repricing:**
  ```bash
  poetry run pytest scripts/tests/ui_golden/test_ui_pricing_d9.py -v -p no:cacheprovider
  ```
- **Role-Based Access Control (7 Personas) & Cross-Tenant Isolation:**
  ```bash
  poetry run pytest scripts/tests/ui_golden/test_ui_auth_access.py -v -p no:cacheprovider
  ```

---

## 4. Test Selector & Page Object Conventions

- **Stable Selectors Only:** Always target `[data-testid="..."]` attributes registered in `backend/scripts/tests/ui_golden/testids.py` or semantic ARIA roles (`role="dialog"`, `role="tab"`). Never use brittle Tailwind class chains in XPath/CSS selectors.
- **Seeded `logismart-test` Personas (`auth.py`):**
  - `owner` (`owner@logismart.in`), `admin` (`admin@logismart.in`)
  - `operations` (`operations@logismart.in`), `support` (`support@logismart.in`), `readonly` (`readonly@logismart.in`)
  - `customer_b2c` (`customerb2c@logismart.in`), `customer_b2b` (`customerb2b@logismart.in`), `b2b_onboarding` (`b2bonboarding@logismart.in`)
