---
name: delhivery-parity
description: Enforces Delhivery One (one.delhivery.com) product and API parity across B2C Express and B2B Cargo flows, using .agents/knowledge/delhivery-one.md and official help.delhivery.com slugs.
---

# Delhivery One Parity Skill (`delhivery-parity`)

Use this skill whenever you plan, design, implement, or review any feature touching **booking, pricing/rates, pickup requests (PUR/manifests), shipment lifecycle stages, NDR exceptions, RTO, hub weight discrepancy, COD remittance, wallet recharges, GST billing (`TAX_INVOICE` / `CREDIT_NOTE` / `DEBIT_NOTE`), or shipping labels/LRs**.

## 1. Read First (Mandatory Context)

1. **[`.agents/knowledge/delhivery-one.md`](../../knowledge/delhivery-one.md):** Master reference containing:
   - The **Delhivery Help-Center Slug $\rightarrow$ Naviera Module/Route Map** (§3).
   - **Delhivery B2C (`track.delhivery.com`) & B2B LTL (`ltl-clients-api.delhivery.com`) API wire facts**, P0 production probe findings (`cgm` volumetric weight in grams, `charge_COD` inside `gross_amount`, cumulative `ss=RTO`, `total_amount` inclusive of 18% GST, `B2CFallbackDelhiveryB2BApi`), and rate-limit/cache rules (§4).
   - **Locked Pricing & Commercial Decisions** (`0%` Delhivery default markup, `20%` Prime default markup, Door vs. Godown `₹0` door fee, `409 PRICE_CHANGED` re-price on Book, server-only `carrier_cost`) (§5).
   - **Admin $\leftrightarrow$ Delhivery 3-Step Co-ordination Playbook** (§6).
2. **[`docs/client/DELHIVERY_VS_LOGISMART.md`](../../../docs/client/DELHIVERY_VS_LOGISMART.md):** Documents every intentional Logismart simplification over `one.delhivery.com`.

---

## 2. Step-by-Step Parity Workflow

### Step 1: Identify the Official Delhivery Help Article Slug
Check the Feature Map in [`.agents/knowledge/delhivery-one.md`](../../knowledge/delhivery-one.md) or search the official index at `https://help.delhivery.com/llms.txt`.

### Step 2: Inspect the Article Specification
- If the local snapshot directory `.agents/knowledge_base/delhivery_one/` exists on this machine, read `.agents/knowledge_base/delhivery_one/<slug>.md`.
- Otherwise, fetch the raw markdown directly from `https://help.delhivery.com/docs/<slug>.md`.
- *(Never commit verbatim copies of third-party help articles into the tracked repo; keep summaries and links in `.agents/knowledge/delhivery-one.md`.)*

### Step 3: Check Intentional Logismart Simplifications
Verify in [`docs/client/DELHIVERY_VS_LOGISMART.md`](../../../docs/client/DELHIVERY_VS_LOGISMART.md) whether Logismart intentionally differs (for example: 3-click wizard with collapsed `< ₹50,000` compliance box, UPI QR + UTR maker-checker wallet top-up instead of PG redirect, or Logismart Prime 18-zone Delhi-NCR rate matrix alongside Delhivery B2B Cargo).

### Step 4: Enforce Core Parity Invariants in Code
- **B2C vs. B2B Split:**
  - B2C (`ServiceFlow.B2C`): Forward & Reverse allowed; volumetric divisor `5000`; `500 g` min (`0.5 kg` slabs); `4×6 in` thermal AWB label.
  - B2B (`ServiceFlow.B2B`): Forward-only (`ShipmentType.REVERSE` rejected); volumetric divisor `4500`; `20 kg` min (Delhivery B2B) / `50 kg` min (Prime); 3-copy A4 Lorry Receipt docket + box stickers; **Door Delivery** vs. **Godown Self-Pickup** (`prime_delivery_type`).
- **Money & GST Parity:**
  - Zero frontend math (`npm run test:audit`).
  - All post-booking price changes (edits, hub measurements, weight disputes, admin overrides) go exclusively through `RepricingService.apply()` (`backend/app/services/repricing.py`), which atomically adjusts the wallet and issues a GST `DEBIT_NOTE` or `CREDIT_NOTE`.
  - Never expose `carrier_cost`, `markup_percent`, or internal `transporter_name` in customer or public responses.
- **Lifecycle & NDR/RTO Parity:**
  - All status transitions validated by `ShipmentLifecycleMachine` (`backend/app/services/shipment_lifecycle.py`).
  - Pre-pickup cancel (`OPEN`/`ASSIGNED`) $\rightarrow$ `CANCELLED` + 100% wallet refund + GST `CREDIT_NOTE`.
  - Post-pickup cancel $\rightarrow$ `RTO_INITIATED` (no freight refund).
  - NDR actions (`REATTEMPT`, `RTO`, `EDIT_DETAILS`) require `status == EXCEPTION`, `ndr_status == OPEN`, and `ndr_attempt_count < 3`.

### Step 5: Cite the Slug
In your implementation plan, PR description, and handover notes, cite the Delhivery article slug: e.g., `Parity: [create-forward-order](https://help.delhivery.com/docs/create-forward-order)`.
