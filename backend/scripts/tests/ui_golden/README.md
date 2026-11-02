# UI click-through golden layer (`ui_golden`)

Ship-readiness plan items E3/E4. Journeys (U01 to U40) arrive in wave 4. This folder holds the framework and one smoke test.

## Run

```bash
cd backend
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
poetry install --with e2e                      # once: pytest-playwright + pypdf
poetry run pytest scripts/tests/ui_golden -m ui -s
```

You need:
- The visible Chrome listening on `127.0.0.1:9224` (`UI_CDP_URL`). No browser download: we attach over CDP and only close the contexts we open.
- Frontend on `:3000` (`UI_FRONTEND_URL`) and backend on `:8000` (`UI_API_URL`).
- For logged-in tests: the seeded `logismart-test` tenant and `GOLDEN_TEST_PASSWORD`. Without them those tests skip. The smoke test needs neither.
- Optional: `UI_SLOW_MO_MS` (default 300) and `UI_HIGHLIGHT_MS` (default 450). Set both to 0 for a fast headless-style run.

## Pieces

| File | Role |
| --- | --- |
| `conftest.py` | Shadows the parent unit-test fixtures. Loads `ui_fixtures.py` only if Playwright is installed. Adds the `ui` marker. |
| `ui_fixtures.py` | `cdp_session`, `step_banner`, `ui_tabs` (anonymous), `role_tabs` (logged in), `ui_tenant` (guarded, holds the golden run lock, no reset), `db_oracle` |
| `browser_session.py` | CDP connect with `slow_mo`; one context per tab (1440×900 or 390×844 mobile) |
| `hud.py` | Top banner `J09 step 3/7: Book shipment` (re-drawn after every page load) and an outline flash before each click or fill |
| `network_guard.py` | Fails on unexpected HTTP ≥ 400 from app origins, `console.error` (incl. hydration) and uncaught page errors. Declare expected ones with `guard.expect_http(regex, status)` |
| `auth.py` | One real password login per account, then `storage_state` cached in `/tmp/naviera_ui_golden_<slug>_<email>.json` (0600, 45 min). Guards: allow-listed slug, `environment == "test"`, canonical test actor, never a protected live email |
| `db_oracle.py` | `READ ONLY` transaction, always `tenant_id == logismart-test`, always rolled back |
| `money.py` | `parse_rupees("₹1,23,456.50")`, `assert_screen_money_equals_db(locator, db_value)`: exact to the paisa, half-up |
| `pdf.py` | `download_via_click` + `pdf_text(path).assert_contains(expected_tokens)` (pypdf) |
| `testids.py` | Single registry of `data-testid` names |
| `pages/` | One page object per screen: login, B2C/B2B booking, shipment detail, edit + preview, measurement dialog, pickup list + dispatch dialog (actual pieces), mobile `/ops`, wallet, invoices/notes, remittances, weight mismatch |

## `data-testid` convention

`<page>.<section>.<element>`. The first two parts are lowercase kebab-case. Dynamic ids go last and are kept exactly as shown on screen (`pickup-dispatch.row.<AWB>.actual-pieces`). Put money testids on the element whose text is **only** the formatted amount (`₹1,234.50`). The full list is in `testids.py`. Frontend owners add the attributes on the screens they touch.

## Journey skeleton (wave 4)

```python
async def test_u05_edit_weight_rebills(role_tabs, ui_settings, step_banner, db_oracle):
    tab = await role_tabs.as_role(CUSTOMER_B2C_EMAIL)
    await step_banner.show(tab.page, "U05", 1, 3, "Open edit page")
    edit = await ShipmentEditPage(tab.page, ui_settings, step_banner).open_edit(shipment_id)
    await edit.set_package_weight(0, "2.0")
    preview = await edit.read_preview()
    await edit.save()
    stored = await db_oracle.shipment(awb)
    assert preview.new_total == stored.total_logistics_cost
```
