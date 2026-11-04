# Delhivery One Knowledge Base & Integration Reference (`.agents/knowledge/delhivery-one.md`)

> **Purpose:** Persistent architectural and domain reference so AI agents and engineers never need the user to re-explain how **Delhivery One (`one.delhivery.com`)** works, how **Logismart** integrates with Delhivery's B2C and B2B APIs, or why specific pricing and operational decisions were made.
> - **Companion Skill:** [`../skills/delhivery-parity/SKILL.md`](../skills/delhivery-parity/SKILL.md)
> - **Client Simplification Guide:** [`../../docs/client/DELHIVERY_VS_LOGISMART.md`](../../docs/client/DELHIVERY_VS_LOGISMART.md)

---

## 1. Origin & Product Parity Mandate

1. **Business Model:** **Logismart** (`https://logismart.naviera.com`) is a Delhivery franchise and multi-carrier 3PL partner built on **Naviera**. Customers book **B2C Express Parcels** and **B2B Heavy Cargo (LTL)** on Logismart, pay via a prepaid wallet, and receive GST-compliant invoices—while Logismart dispatches shipments through Delhivery One or its own **Logismart Prime** truck network.
2. **Delhivery One Parity Rule:** Every screen, order stage, navigation item, form field, terminology, and financial rule in Naviera must mirror **Delhivery One (`https://one.delhivery.com`)**, unless an explicit Logismart-specific simplification is documented in [`../../docs/client/DELHIVERY_VS_LOGISMART.md`](../../docs/client/DELHIVERY_VS_LOGISMART.md).
3. **Unexplained Deviations Are Defects:** Any plan, PR, or code review that alters a booking, pickup, NDR, RTO, weight discrepancy, COD, wallet, or GST flow must state the Delhivery One equivalent and cite the official help article slug.

---

## 2. Official Delhivery Sources & Verification Procedure

| Source | URL / Location | What It Covers |
| :--- | :--- | :--- |
| **Help Center LLM Index** | `https://help.delhivery.com/llms.txt` | Master index of all official Delhivery One panel documentation slugs. |
| **Help Center Raw Markdown** | `https://help.delhivery.com/docs/<slug>.md` | Authoritative UI workflows, rules, weight slabs, NDR/RTO policies, and wallet/billing behavior. |
| **Local Help Snapshot (Git-Ignored)** | `.agents/knowledge_base/delhivery_one/<slug>.md` | Local cached copies of help articles (kept git-ignored as third-party text; use when present locally). |
| **Client Developer Portal** | `https://one.delhivery.com/developer-portal/document/{b2c\|b2b}/detail/<slug>` | Wire-level REST API specs, headers, rate limits, and error codes for B2C Express and B2B LTL. |
| **Delhivery Docs MCP** | `https://mcp-client-integration.delhivery.com/mcp` | Official B2C OpenAPI specification lookup (`get_api_documentation`, `get_doc`). |

### Parity Verification Procedure for Agents
1. Look up the relevant `<slug>` in the **Feature Map (§3)** below or via `https://help.delhivery.com/llms.txt`.
2. Read `.agents/knowledge_base/delhivery_one/<slug>.md` (if present locally) or fetch `https://help.delhivery.com/docs/<slug>.md`.
3. Check [`../../docs/client/DELHIVERY_VS_LOGISMART.md`](../../docs/client/DELHIVERY_VS_LOGISMART.md) to see if Logismart intentionally simplifies that step.
4. Cite `[<slug>](https://help.delhivery.com/docs/<slug>)` in your implementation plan, code comments, or review.

---

## 3. Delhivery One $\rightarrow$ Naviera Feature & Route Map

| Domain Area | Delhivery Help Article Slugs (`https://help.delhivery.com/docs/<slug>.md`) | Naviera Frontend Routes (`frontend/src/app/[tenant_slug]/`) | Naviera Backend Modules (`backend/app/`) | Key Parity & Simplification Rules |
| :--- | :--- | :--- | :--- | :--- |
| **B2C Forward Booking** | `create-forward-order` | `(app)/shipments/new/forward` | `api/v1/endpoints/shipments.py`, `services/shipment.py`, `services/pricing/booking.py` | 3-click wizard. Optional HSN/Invoice/E-Way Bill card collapsed by default when value `< ₹50,000` (mandatory at `≥ ₹50,000`). Compares **Delhivery Surface** vs. **Delhivery Express**. |
| **B2C Reverse Pickup** | `create-reverse-order`, `reverse-shipments` | `(app)/shipments/new/reverse` | `services/shipment.py` (`ShipmentType.REVERSE`) | Prepaid only (`COD` blocked on reverse). Quotes Delhivery `ss=DTO`. Optional return QC parameters (`qc_check_required`, item description, serial/IMEI). |
| **B2B Heavy Cargo (LR) Booking** | `b2b-order-creation`, `manifest-lr-via-delhivery-one-panel`, `freight-charges` | `(app)/b2b/shipments/new/forward` | `services/pricing/prime.py`, `services/pricing/delhivery_b2b.py` | Forward-only (`REVERSE` blocked for B2B). Multi-box lines (`count`, `weight`, `L×B×H`), mandatory Invoice # & Cargo Value (`EWAY_BILL` required `≥ ₹50,000`). Compares **Logismart Prime** (Door Delivery vs. Godown Self-Pickup at `₹0` door fee) and **Delhivery B2B Cargo**. |
| **Order Stages & Lifecycle** | `order-stages-states`, `tracking-b2b-orders` | `(app)/shipments`, `(app)/b2b/shipments`, `track/[id]` | `services/shipment_lifecycle.py` (`ShipmentLifecycleMachine`) | Single status rail: `OPEN` (Manifested) $\rightarrow$ `ASSIGNED` (In PUR) $\rightarrow$ `PICKED` $\rightarrow$ `IN_TRANSIT` $\rightarrow$ `OUT_FOR_DELIVERY` $\rightarrow$ `COMPLETED` (Delivered), plus `EXCEPTION` (NDR), `RTO_INITIATED` $\rightarrow$ `RTO_IN_TRANSIT` $\rightarrow$ `RTO_DELIVERED`, and `CANCELLED`. |
| **Cancellation Rules** | `cancel-an-order` | `(app)/shipments/[id]` | `services/shipment.py`, `services/repricing.py` | Pre-pickup (`OPEN` / `ASSIGNED`) transitions to `CANCELLED`, refunds 100% of freight + GST to wallet, and issues a GST `CREDIT_NOTE`. Post-pickup (`PICKED` / `IN_TRANSIT` / `OUT_FOR_DELIVERY` / `EXCEPTION`) converts to `RTO_INITIATED` with no freight refund. |
| **Pickup Requests (PUR / Manifests)** | `create-a-pickup-request`, `creating-pur-to-get-material-picked-for-manifested-lrs` | `(app)/pickups`, `(app)/b2b/pickup-requests` | `api/v1/endpoints/manifests.py`, `services/manifests.py` | Links `OPEN` shipments at a warehouse + date + time slot (`OPEN` $\rightarrow$ `ASSIGNED`). Also supports B2B **Blind Pickups** (`is_blind_pickup=True`, `total_boxes=N`) before individual LRs are created. |
| **NDR / Delivery Exceptions** | `non-delivery-management-ndr` | `(app)/exceptions`, `(app)/b2b/exceptions` | `services/ndr_rules.py`, `services/exceptions.py`, `scripts/temporal_hooks_worker.py` | Actionable only when `status == EXCEPTION` (the reason is `ndr_reason`). Max **3** failed delivery attempts (`ndr_attempt_count`, `ndr_rules.MAX_NDR_ATTEMPTS`), then auto-RTO. Allowed `NdrAction`s (`REATTEMPT`, `RETURN_TO_ORIGIN`, `UPDATE_CONSIGNEE`, `BOOK_APPOINTMENT`, …) depend on the reason and flow (`ndr_rules.py`). No time-based auto-escalation: `temporal_hooks_worker.py` only *raises* holds (expired appointment → `APPOINTMENT_NEEDED`; In transit, goods ≥ ₹50,000, no update > 72 h → `EWAY_BILL_MISSING`). |
| **Return to Origin (RTO)** | `return-to-origin-rto` | `(app)/shipments/[id]`, `(app)/exceptions` | `services/shipment_lifecycle.py`, `services/repricing.py` | Once in `RTO_INITIATED` / `RTO_IN_TRANSIT` / `RTO_DELIVERED`, shipment can never transition to `COMPLETED`. |
| **Rate Calculator & Volumetric Weight** | `rate-calculator`, `rate-card`, `calculating-volumetric-weight`, `b2b-serviceability-rate-calculator` | `(marketing)/rate-calculator`, `(app)/rate-calculator`, `(app)/b2b/rate-calculator` | `api/v1/endpoints/pricing.py`, `services/pricing/quote_service.py`, `services/pricing/weights.py` | B2C volumetric divisor `5000` (`500 g` min, `0.5 kg` slabs). B2B volumetric divisor `4500` (`20 kg` min for Delhivery B2B, `50 kg` min for Prime). Zones `A`–`F` (B2C) and 18 city/PIN zones (Prime). |
| **Weight Discrepancy & Hub Audit** | `weight-discrepancy` | `(app)/weight-mismatch`, `(app)/shipments/[id]` | `services/shipment.py`, `services/delhivery_modules.py`, `services/repricing.py` | Hub `MeasurementDialog` or Weight Mismatch dispute resolution triggers `RepricingService.apply()`, atomically debiting/refunding the wallet delta and issuing a GST `DEBIT_NOTE` or `CREDIT_NOTE`. |
| **Wallet & Recharges** | `wallet-and-billing`, `recharge-delhivery-wallet` | `(app)/wallet` | `api/v1/endpoints/wallet.py`, `services/wallet.py` | Prepaid wallet ledger (`wallet_transactions`). Customers recharge via dynamic **UPI QR + 12-digit UTR** (staff maker-checker approval queue) or Admin **Record Offline Credit** (NEFT/IMPS/RTGS/Cash). |
| **GST Invoices, Credit & Debit Notes** | `invoices-and-credit-notes` | `(app)/invoices` | `services/gst_documents.py` | Sequential FY-scoped GST documents (`SAC 996812` Courier / `SAC 996511` Road GTA, 18% GST: `9% CGST + 9% SGST` intra-state or `18% IGST` inter-state) + monthly consolidated `BillingInvoice` statements. |
| **COD Remittance** | `cod-remittance` | `(app)/remittances` | `services/cod_payout.py`, `services/delhivery_modules.py` | `door_collectible` computed solely by `cod_payout.py` and frozen on `COMPLETED`. Staff settles remitted COD batches (`UTR` + bank proof) into customer wallets or bank payouts. |
| **Shipping Labels & LR Dockets** | `shipping-labels`, `print-lr-copy-and-labels` | `(app)/shipments/[id]` (`Print Label`) | `services/label.py` | B2C generates `4×6 in` thermal AWB sticker PDF. B2B (`≥ 20 kg` or `service_flow == B2B`) generates 3-copy A4 Lorry Receipt docket (`Consignor`, `Consignee`, `Driver Copy`) + per-box stickers (`-B1..N`). |
| **Appointment Delivery** | `appointment-based-delivery` | `(app)/b2b/appointments` | `api/v1/endpoints/appointments.py`, `services/appointments.py` | B2B time-window delivery scheduling (`PENDING`, `CONFIRMED`, `RESCHEDULED`, `COMPLETED`, `CANCELLED`). |
| **Saved Warehouses / Addresses** | `manage-warehouses` | `(app)/address-book` | `api/v1/endpoints/addresses.py`, `services/addresses.py` | Personal (`USER`) and team (`TENANT`) address book. Shipments store immutable snapshot copies (`is_saved=False`) so editing a shipment never mutates saved warehouse records. |
| **Support Tickets** | `support-tickets`, `raising-support-tickets-for-b2b-shipments` | `(app)/support` | `api/v1/endpoints/delhivery_modules.py`, `services/delhivery_modules.py` | Threaded support tickets linked to AWB/LR numbers (`OPEN`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`). |
| **Settings, Team & API Setup** | `settings-and-users`, `api-token-generation` | `(app)/settings`, `(app)/settings/prime-lanes`, `(app)/team` | `api/v1/endpoints/tenants.py`, `api/v1/endpoints/pricing_prime.py`, `api/v1/endpoints/users.py` | 7 RBAC personas (`owner`, `admin`, `operations_user`, `support_user`, `read_only_user`, B2C `customer`, B2B `customer`), Pricing Policy markups, Prime Lane CSV import/export, and settings audit history. |

---

## 4. Delhivery Live API Architecture & Production Findings (Sanitized)

### 4.1 Two Distinct Delhivery APIs, Hosts & Auth Schemes

| Dimension | B2C Express (`SURFACE` / `EXPRESS`) | B2B Cargo / LTL (`DELHIVERY_B2B`) |
| :--- | :--- | :--- |
| **Production Base URL** | `https://track.delhivery.com` | `https://ltl-clients-api.delhivery.com` |
| **Staging Base URL** | `https://staging-express.delhivery.com` *(returns `₹0` for all prices; price tests must use prod read-only calls or `FakeDelhiveryApi`)* | `https://ltl-clients-api-dev.delhivery.com` *(has no pricing file; returns `Pricing File Not exist`)* |
| **Authentication Header** | `Authorization: Token <static_token>` *(literal prefix `Token`, never `Bearer`; token never expires unless regenerated in the panel)* | `Authorization: Bearer <jwt>` obtained from `POST /ums/login` (`24h` lifetime; refresh server-side at `~23h`) |
| **Rate Limit Unit** | Requests per 5-minute window per **egress IP** (`50–150 req / 5 min / IP` for pricing; `750 req / 5 min` global WAF) | `100 req / 5 min / IP` for `/ums/login` and `/freight/estimate` (wrong password locks account for 10 min) |
| **Token Rotation Hazard** | Clicking **"Request Live API Token"** in `one.delhivery.com` ▸ **Settings ▸ API Setup** invalidates the existing token **immediately**. | LTL password expires every 180 days; reset via `POST /forgot-password` (`{"username": "<ACCOUNT_USERNAME>"}`). |

### 4.2 Logismart Delhivery Account Structure (Sanitized)
Logismart's Delhivery One master login includes multiple sub-accounts in the top-right account switcher:
1. **Domestic Franchise Account (Active for `DELHIVERY_API_TOKEN`):** Supports both **Surface (`md=S`)** and **Express (`md=E`)** rate cards. (By contrast, the Domestic C2C sub-account only has a Surface rate card and returns `₹0` for Express.)
2. **B2B Surface LTL Account (`DELHIVERY_B2B_USERNAME`):** Uses dynamic JWT login (`POST /ums/login`). Static tokens shown on the panel's API Setup page are rejected by `ltl-clients-api.delhivery.com` with `400 Token Decode Error`.

### 4.3 B2C Shipping Charge API (`GET /api/kinko/v1/invoice/charges/.json`)
```http
GET https://track.delhivery.com/api/kinko/v1/invoice/charges/.json?md=S&ss=Delivered&o_pin=122001&d_pin=560001&cgm=500&pt=Pre-paid
Authorization: Token <DELHIVERY_API_TOKEN>
```

**Five Production-Verified Rules (Implemented in `backend/app/services/pricing/delhivery.py`):**
1. **`pt` is Mandatory & Case-Sensitive (`Pre-paid` or `COD`):** Omitting `pt` causes production to return `0` for every charge field.
2. **Dimensions (`l,b,h`) Are Ignored by the Endpoint:** Passing `l,b,h` query parameters does not alter `charged_weight`. Naviera computes volumetric weight ($\frac{L \times B \times H\text{ (cm)}}{5000}$) per package in `backend/app/services/pricing/weights.py` and sends `cgm = max(actual_grams, volumetric_grams)` rounded up to `500 g` slabs.
3. **`charge_COD` Is Bundled Inside `gross_amount` When `pt=COD`:** Base forward freight (`charge_DL`) is identical between `Pre-paid` and `COD`, while `pt=COD` adds Delhivery's `charge_COD` into `gross_amount`. Naviera quotes `pt=Pre-paid` (or strips `charge_COD`) for carrier freight and applies Logismart's own configurable COD fee (`cod_fee_fixed` / `cod_fee_percent`) in `SellPriceCalculator`.
4. **`ss=RTO` Returns Cumulative Charges (Forward + Return):** Calling `ss=RTO` returns `gross_amount` containing **both** `charge_DL` (forward) and `charge_RTO` (return). The incremental return charge is therefore `rto_response.gross_amount - delivered_response.gross_amount`.
5. **`total_amount` Already Includes 18% GST:** Delhivery returns `gross_amount` (pre-tax) and `tax_data: {CGST, SGST, IGST}` where `total_amount = gross_amount + tax`. Naviera takes pre-tax `gross_amount` as `carrier_cost`, applies Logismart's markup in `SellPriceCalculator`, and adds 18% GST once.

### 4.4 B2B Cargo Pricing (`DELHIVERY_B2B_SURFACE`) & Production B2C-Token Fallback
- **Native LTL Client (`LiveDelhiveryB2BApi` in `backend/app/services/pricing/delhivery_b2b_client.py`):** Calls `POST /ums/login` $\rightarrow$ `POST /freight/estimate` when both `DELHIVERY_B2B_USERNAME` and `DELHIVERY_B2B_PASSWORD` are set. Only on this path do Delhivery's LTL weight rules (volumetric divisor `4500`, `20 kg` minimum chargeable weight) apply; Delhivery applies them server-side and `FakeDelhiveryB2BApi` mirrors them.
- **B2C-Token Fallback (`B2CFallbackDelhiveryB2BApi` in `backend/app/services/pricing/delhivery_b2b.py`) — what production runs today:** When `DELHIVERY_B2B_PASSWORD` is empty and `DELHIVERY_B2C_TOKEN` is set, `delhivery_b2b_api_for()` prices B2B on the **B2C Surface rate card**: one `GET /api/kinko/v1/invoice/charges/.json` call (`md=S`, `ss=Delivered`, `pt=Pre-paid`) with `cgm = max(dead weight, Σ L×W×H×boxes / 5000)` rounded up to the `500 g` slab, i.e. the B2C divisor `5000` and **no `20 kg` minimum**. Freight = `gross_amount − charge_COD`; ROV = `max(0.1 % × invoice, ₹100)` only at carrier's risk; GST `18 %` on top. Setting `DELHIVERY_B2B_PASSWORD` switches to the native LTL client and its rules.
- **Which tenants get which client (env-driven, `delhivery_client.is_live_tenant` / `is_fake_tenant`):** live for the tenant in `DELHIVERY_TENANT_ID` and every slug in `DELHIVERY_LIVE_TENANT_SLUGS` (Render: `logismart,logismart-test`); the deterministic `FakeDelhiveryApi` / `FakeDelhiveryB2BApi` only for slugs in `DELHIVERY_FAKE_TENANT_SLUGS`, which the test harness (`run_golden.sh`, `scripts/tests/conftest.py`, `golden_env.py`) sets to `logismart-test` so in-process golden/unit tests never call Delhivery. The fake also refuses any tenant outside `FAKE_PROVIDER_TENANT_SLUGS`, so it can never price live `logismart`.

### 4.5 Price Cache (`delhivery_price_cache`) & Server-Side Re-Price on Book
- **Cache Table (`backend/app/repositories/delhivery_price_cache.py`):** Scoped by `(tenant_id, cache_key)` where `cache_key` encodes `(origin_pin, dest_pin, mode, status, payment_type, weight_slab_grams)` (B2B: `B2B|source|consignee|<body hash>`). Live answers are stored under a `LIVE|` prefix (`delhivery.tenant_cache_key`) so fake rows written by local golden runs and live rows written by the deployed app never mix in the shared database.
  - Fresh reuse for quotes: `30 min` (`FRESH_MAX_AGE`); Book always asks Delhivery first.
  - Fallback when Delhivery is down / throttled: stored answer `≤ 24 h` (`FALLBACK_MAX_AGE`), marked `priced_from_cache=True`.
- **Re-Price on Book (`409 PRICE_CHANGED`):** When a customer clicks **Book for ₹X**, the frontend passes `expected_total`. `ShipmentService` re-evaluates the quote server-side; if the total changed by more than `₹0.01`, the API returns `HTTP 409 PRICE_CHANGED` with the updated quote so the customer explicitly confirms the new total before wallet debit.

---

## 5. Locked Commercial & Pricing Decisions

| Decision | Setting / Implementation | Rationale |
| :--- | :--- | :--- |
| **Delhivery B2C & B2B Default Markup** | `0%` (`PERCENT` = `0`, `FLAT` = `₹0` in `pricing_policy`) | Matches Delhivery One's exact price out of the box (Logismart claims input GST credit); Admin can adjust `%` or `₹` markup per option anytime in **Settings ▸ Pricing**. |
| **Logismart Prime Default Markup** | `20%` (`prime_default_markup_percent = 20`) | Master rate sheet (`Sheet1`, 75 transporter lanes from Delhi NCR to 18 destination zones / `558` slabs) represents wholesale transporter cost; 20% default margin yields customer sell price before 18% GST. |
| **Prime Door Delivery vs. Godown Pickup** | `prime_delivery_type` = `DOOR` or `GODOWN` | Customers can choose **Godown / Hub Self-Pickup** (`₹0` door delivery fee) or **Door Delivery** (`₹150` / per-kg door delivery fee) on Step 1 and toggle live on Step 2. |
| **COD Policy** | `allow_cod` toggle + `cod_fee_fixed` / `cod_fee_percent` | Logismart charges one transparent COD fee ($\max(\text{fixed}, \% \times \text{goods value})$) and absorbs Delhivery's internal `charge_COD`. Prime B2B is Prepaid-only. |
| **Wholesale Cost Secrecy** | `payment_details.carrier_cost` & `transporter_name` | Server-only / Staff-only; stripped from all customer and public tracking schemas (`test_09` & `test_11` assert `carrier_cost` never leaks). |

---

## 6. Admin $\leftrightarrow$ Delhivery One 3-Step Co-ordination Playbook

Because MVP booking generates an immediate `LOGISMART-XXXXXXXX` AWB/LR and local PDF label while physical carrier dispatch happens on `one.delhivery.com`, staff follow the built-in **3-Step Co-ordination Playbook** (available in the top header **Delhivery Guide** modal and on every `/shipments/[id]` page):

1. **Step 1 — Customer Books on Logismart:** Customer compares live rates, clicks **Book**, pays from their Logismart Wallet, and receives an instant `TAX_INVOICE` and shipping label (`LOGISMART-XXXXXXXX`).
2. **Step 2 — Staff Dispatches on `one.delhivery.com` (or Prime Fleet):** Operations/Admin creates the corresponding physical order on `one.delhivery.com` (or assigns a Prime truck) and copies the 14-digit Delhivery AWB/LRN and Delhivery's actual billed freight.
3. **Step 3 — Staff Records Carrier AWB & Actual Cost on Logismart:** On `/shipments/[id]`, staff pastes `delhivery_awb` and `actual_carrier_cost` into **Carrier Booking & Actual Cost** (which calculates live net profit margin and flags any cost variance). If the hub re-weighs the parcel or the final price needs adjustment, staff uses **Record Measurement** or **Override / Adjust Shipment Price** (`RepricingService`), which atomically settles the wallet delta and issues a GST **Debit Note** or **Credit Note**.
