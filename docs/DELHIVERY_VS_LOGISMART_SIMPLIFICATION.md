# Delhivery One (`one.delhivery.com`) vs. Logismart — Side-by-Side Comparison, UX Simplification & 15-Minute Training Guide

> **Purpose:** Anyone who has used `one.delhivery.com` can use Logismart on Day 1 without learning a new mental model.
> - **For Customers (B2C & B2B Shippers):** Logismart mirrors `one.delhivery.com` 1:1 in navigation, order statuses, pickup requests, NDR exceptions, wallet, COD remittances, and GST invoices.
> - **For Logismart Admin & Staff:** Logismart includes 4 operator controls that a normal `one.delhivery.com` shipper never sees—because **Logismart is the platform operator** selling shipping to its own customers.

---

## 1. Side-by-Side Screen & Term Mapping (`one.delhivery.com` vs. Logismart)

### 1.1 Customer Workspace (1:1 Parity with `one.delhivery.com`)

| `one.delhivery.com` Screen / Term | Logismart Route & Menu Label | Delhivery Help Center Source Slug | What the Customer Does Here |
| :--- | :--- | :--- | :--- |
| **Account Switcher (`Domestic` vs `B2B Surface`)** | Header Flow Switcher (`B2C Express` vs `B2B Heavy Cargo`) | `start-your-shipping-journey-with-delhivery-one`, `b2b-cargo-orders` | Switch between B2C parcels (`0.1–25 kg`) and B2B multi-box heavy cargo (`LRs`). |
| **Home** (`/v2/home`) | **Home** (`/dashboard` & `/b2b/dashboard`) | `orders`, `domestic-orders` | View 30-day order funnel (`Pre-Shipping`, `In Transit`, `Delivered / RTO`), NDR alerts, and Wallet summary. |
| **Orders & Pickups ▸ Forward Orders** (`/v2/shipments/forward/ready-to-ship`) | **Orders & Pickups ▸ Orders** (`/shipments` & `/b2b/shipments`) | `domestic-orders`, `b2b-cargo-orders`, `export-orders` | View `Ready to Ship`, `Ready for Pickup`, `In Transit`, `RTO`, `Delivered`, print 4×6 / A4 labels, and export CSV. |
| **Orders & Pickups ▸ Create Shipment** (`/v2/shipments/forward/create`) | **New Forward Shipment** (`/shipments/new/forward` & `/b2b/shipments/new/forward`) | `create-forward-order`, `ship-forward-order`, `b2b-order-creation` | Enter Pickup/Drop address, Box weight/dimensions, and Goods Value → compare live rates → book from Wallet. |
| **Orders & Pickups ▸ Reverse Orders (DTO)** (`/v2/shipments/reverse/ready-for-pickup`) | **Orders ▸ Reverse / Return (DTO)** (`/shipments/new/reverse`) | `reverse-ordersdto` | Book a reverse return pickup from the end-consumer back to the seller warehouse (with optional Doorstep QC). |
| **Orders & Pickups ▸ Pickup Requests** (`/v2/pickup-requests/domestic`) | **Orders & Pickups ▸ Pickup Requests** (`/pickup-requests` & `/b2b/pickup-requests`) | `pickup-request`, `b2b-pickup-request` | Schedule a warehouse truck/rider pickup (`PUR`) for manifested orders or book a B2B Blind Pickup. |
| **Manage Appointments (B2B)** | **Manage Appointments** (`/b2b/appointments`) | `b2b-appointments`, `manage-appointments` | Book consignee dock/mall delivery appointments (`PO number`, `PO expiry >= appointment date`, time slot). |
| **Delivery Exceptions (NDR)** | **Delivery Exceptions** (`/delivery-exceptions` & `/b2b/delivery-exceptions`) | `exception-ndr`, `b2b-exceptions-management` | Submit **Reattempt** (with updated consignee phone/address/date) or **Return to Origin (RTO)** instructions. |
| **Finances ▸ Wallet** | **Finances ▸ Wallet** (`/wallet`) | `unified-wallet-faqs`, `b2b-wallet`, `delhivery-miles-wallet` | Recharge via UPI QR + 12-digit UTR, view live balance, download Advance Receipt Vouchers & Passbook CSV. |
| **Finances ▸ COD Remittances** | **Finances ▸ Remittances** (`/finances/remittances`) | `cod-remittance` | Track delivered COD orders, batch UTR payouts to bank account, and download Remittance Advice PDF + CSV. |
| **Finances ▸ Invoices** | **Finances ▸ Invoices** (`/finances/invoices`) | `invoices`, `gst-compliant-shipping-label-cum-invoice-help-guide` | Download SAC `996812` GST Tax Invoices, GST Credit Notes (refunds), and GST Debit Notes (weight/price adjustments). |
| **Disputes ▸ Weight Mismatch** | **Disputes ▸ Weight Mismatch** (`/disputes/weight-mismatch`) | `weight-dispute`, `calculating-volumetric-weight` | View hub weight audits (`Declared kg` vs `Charged kg`), ₹ delta, and raise a claim with scale/label photos within 7 days. |
| **Rate Calculator & Serviceability** (`/v2/rate-calculator`) | **Rate calculator & serviceability** (`/rate-calculator` & `/b2b/rate-calculator`) | `rate-calculator`, `b2b-serviceability-rate-calculator` | Check pincode serviceability, compare Surface vs Express (B2C) or Prime vs Delhivery Cargo (B2B), and hand off to booking. |
| **Support** (`/v2/support/support-tickets/open`) | **Support** (`/support`) | `support-tickets`, `b2b-support-tickets`, `resolving-claims` | Raise AWB-linked support tickets or Lost/Damaged claims (capped at declared value / policy cap). |
| **Settings ▸ Pickup Locations** | **Settings ▸ Pickup Addresses / My Facilities** (`/address-book`) | `pickup-locations`, `pickup-locations-1` | Save and manage verified warehouses, shops, and frequent consignee addresses. |

---

### 1.2 Staff & Admin Workspace (Why Admin Sees More Than a Customer)

When logged in as **Owner** (`owner@`) or **Admin** (`admin@`), the left sidebar is visually divided into three clear sections so staff never confuse customer screens with operator tools:

| Sidebar Section | Menu Items | Who Sees It | Purpose |
| :--- | :--- | :--- | :--- |
| **1. Daily Shipping & Money** | `Home`, `Orders & Pickups`, `Delivery Exceptions`, `Finances`, `Support`, `Disputes`, `Rate calculator`, `Settings ▸ Pickup Addresses` | Customers + Staff | View all customer shipments, remittances, invoices, weight claims, and support tickets across the tenant. |
| **2. Platform Setup** *(inside Settings)* | `Users` (`/team`), `Workspace Settings` (`/settings`), `Pricing & Prime lanes` (`/settings/prime-lanes`) | Owner / Admin *(Prime Lanes read-only for Staff)* | Manage staff/customer roles & B2B approvals, company GST profile, UPI VPA, service markups, and Prime lane rate cards. |
| **3. Staff & Hub Operations** | `Ops Control Tower` (`/ops`) | Owner, Admin, Operations | First-mile PUR dispatch, hub weight/dimension sorter audit, and last-mile 6-digit OTP delivery & COD cash collection. |

---

## 2. Why Logismart Has 4 Extra Admin Controls (and How We Made Them Effortless)

On `one.delhivery.com`, Delhivery is the carrier and Logismart is the customer.
On **Logismart**, **Logismart is the platform operator** reselling Delhivery B2C/B2B and operating its own **Logismart Prime** B2B network. That means Logismart Admin performs **4 operator actions** that don't exist in a shipper-only portal:

### Control 1: Set Markups & Prime Lane Rates (`Settings ▸ Pricing` & `Settings ▸ Prime Lanes`)
- **Why it exists:** Delhivery returns its wholesale rate (e.g., ₹50.33 Surface). Logismart adds a markup (`%` or `Flat ₹`) before quoting the customer. For **Logismart Prime** (B2B), Logismart maintains its own city-to-city transporter rate table (`rate_per_kg`, `min_freight`, `pickup_charge`, `door_delivery_charge`, `docket_charge`, `FOV`, `fuel %`).
- **How we simplified it:**
  - **Per-service `%` or `Flat ₹` toggle** on `Settings ▸ Pricing` with a before/after confirmation dialog.
  - **1-click `"Download Template CSV"`** on `Settings ▸ Prime Lanes` so Admin can download a ready-to-fill sample CSV, edit rates in Excel, and import with a live diff preview.

### Control 2: Approve UPI Recharges & Record Offline Wallet Credits (`Finances ▸ Wallet`)
- **Why it exists:** Customers either pay via Logismart's direct UPI QR (zero payment-gateway fee, verified via 12-digit UTR) or send money offline via NEFT / IMPS / Cash / Bank Transfer.
- **How we simplified it:**
  - **Maker-Checker Queue:** Pending UPI UTR requests appear at the top of `/wallet` for Admin with 1-click **Approve** or **Reject**.
  - **Record Offline Credit / Bank Transfer:** A single button on `/wallet` where Admin selects the customer's email, enters the ₹ amount and UTR/reference note, and immediately credits their wallet + issues a GST-compliant **Wallet Advance Receipt Voucher**.

### Control 3: Book or Link Carrier AWB (`Shipment Detail ▸ Carrier Booking & Bill`)
- **Why it exists:** When a customer books an order on Logismart, it gets a Logismart tracking ID (`LOGISMART-...`). Logismart staff then either click **Book on Delhivery** (or assign a Prime truck / external AWB) and record what the carrier billed Logismart.
- **How we simplified it:**
  - Right on Shipment Detail (`/shipments/[id]` and `/b2b/shipments/[id]`), the **Carrier Booking & Bill** card shows whether the carrier charged more than the customer paid (`Under-recovery gap`) and offers a 1-click recovery action.

### Control 4: Bidirectional 1-Box Admin Price Override (`Shipment Detail` & `Hub Weight Audit`)
- **Why it exists:** Sometimes a shipment is **overpriced** (Admin wants to give a discount/refund) or **underpriced** (carrier charged extra or hub dimensions changed, so Admin needs to charge more).
- **How we simplified it:**
  - **Single Input (`New Final Price incl. GST: ₹Y`):** Admin does not have to calculate base freight vs. 18% GST or manually edit wallet balances:
    - **If `New Final Price < Current Billed Price` (Overpriced):** Logismart automatically **credits/refunds the ₹ difference back to the customer's wallet** and issues a **GST Credit Note**.
    - **If `New Final Price > Current Billed Price` (Underpriced):** Logismart automatically **debits the ₹ difference from the customer's wallet** (allowing negative balance if needed) and issues a **GST Debit Note**.
  - **Built into Hub Weight/Dimension Audit (`Record Measurement`):** When hub staff enter actual weight/dimensions on `/ops` or Shipment Detail, the pricing engine computes the new quote automatically—and Admin also has an optional **`Override Final Price (₹)`** box right inside the same modal if they want to set a custom final ₹ price in one step.

---

## 3. Summary of UI Simplifications Implemented

1. **Progressive Disclosure on B2C Forward Booking (`/shipments/new/forward`):**
   - **Before:** `HSN Code`, `Invoice Number`, `Invoice Date`, and the multi-file document uploader were all expanded upfront on the primary form, making a simple ₹500 B2C parcel look like a complex commercial customs declaration.
   - **Now:** Standard B2C booking (`<= ₹50,000`) shows only the 3 essentials upfront (**Addresses**, **Box Weight & Dimensions**, **Category & Goods Value**). `HSN Code`, `Invoice Number/Date`, `E-Way Bill`, and `Package Photos` are tucked inside a collapsible **"Optional Tax, Invoice & Compliance Details"** card badged **`Optional (Required only above ₹50,000)`**—which **automatically expands** whenever shipment value exceeds ₹50,000.
2. **Door Delivery vs. Godown Self-Pickup Live Toggle on B2B (`/b2b/shipments/new/forward` & `/b2b/rate-calculator`):**
   - Clear 2-card selector (**`🚚 Door Delivery (To Consignee Doorstep)`** vs **`🏭 Godown / Hub Pickup (₹0 Door Delivery Charge)`**) on Step 1 AND an interactive live toggle at the top of Step 2 (`Choose Shipping Rate`) with itemized `sell_lines` so customers immediately see why Door Delivery costs more than Godown Self-Pickup.
3. **Role-Tailored 3-Step Quick Guides (`ScreenGuideBanner`):**
   - Added a dismissible 3-step **"How this screen works"** banner with a **`Delhivery One Equivalent`** badge on B2C Booking, Shipment Detail, Pricing & Markups, and Operations Control Tower.
   - Clicking **Hide guide** collapses it into a compact **`How it works ?`** pill button (just like `one.delhivery.com`'s header helper button) remembered in `localStorage`.
4. **Sidebar Visual Grouping for Staff (`nav-config.ts` & `nav-menu.tsx`):**
   - Customers see the clean 1:1 `one.delhivery.com` menu.
   - Staff/Admin see clear section headers separating **`DAILY SHIPPING & MONEY`**, **`PLATFORM SETUP`**, and **`STAFF & HUB OPERATIONS`**.

---

## 4. 15-Minute Onboarding Script (For Staff & Customers Who Know `one.delhivery.com`)

### Part A: 5-Minute Customer Tour ("It Works Just Like Delhivery One")
1. **Minute 1 — Switch B2C vs. B2B & Check Wallet (`/dashboard` & `/wallet`):**
   - Point to the top-left **Flow Switcher** (`B2C Express` vs `B2B Heavy Cargo`) — this is identical to switching between `Domestic` and `B2B Surface` in `one.delhivery.com`'s top-right account dropdown.
   - Click the **Wallet Balance pill** in the top header → click **Recharge Wallet** → scan the UPI QR and enter the 12-digit UTR (or pay offline via bank transfer and ask Logismart Admin to credit your wallet).
2. **Minute 2–3 — Book a B2C Parcel in 3 Inputs (`/shipments/new/forward`):**
   - Go to **Orders & Pickups ▸ Orders ▸ Create Shipment**.
   - Select **Pickup Address** and **Receiver Address**, enter **Box Weight & L×B×H**, choose **Product Category**, and enter **Shipment Value (₹)**.
   - Point out the collapsed **"Optional Tax, Invoice & Compliance Details"** bar: *"Below ₹50,000, you don't need HSN or E-Way Bill. Just click **Find Rates**, pick Surface or Express, and click **Book Shipment**."*
3. **Minute 4 — Print Label & Schedule Pickup (`/shipments/[id]` & `/pickup-requests`):**
   - On the booked order page, click **Print Label** (`4×6` thermal PDF) and click **Add to Pickup Request** (`PUR`) to summon the pickup rider/truck.
4. **Minute 5 — Track, NDR & GST Invoices (`/delivery-exceptions` & `/finances/invoices`):**
   - Show **Delivery Exceptions** (click **Reattempt** or **RTO** on any undelivered parcel) and **Finances ▸ Invoices** (download GST Tax Invoices, Credit Notes, and Debit Notes).

---

### Part B: 10-Minute Logismart Admin Tour ("Your 4 Operator Superpowers")
1. **Minutes 6–7 — Set Markups & Prime Lane Rates (`Settings ▸ Workspace Settings ▸ Pricing` & `Settings ▸ Pricing & Prime lanes`):**
   - Open **Settings ▸ Workspace Settings ▸ Pricing**: show how to set `%` or `Flat ₹` markup on `Delhivery Surface`, `Delhivery Express`, `Delhivery B2B Cargo`, and `Logismart Prime`, plus the `COD Fee` (`min ₹` and `%`).
   - Open **Settings ▸ Pricing & Prime lanes**: click **Download Template CSV** to get the sample rate sheet, or click **Edit** on any lane row to update `rate_per_kg`, `door_delivery_charge`, or `docket_charge`.
2. **Minutes 8–9 — Approve UPI Top-Ups & Record Offline Money (`Finances ▸ Wallet`):**
   - Open **Finances ▸ Wallet**:
     - If a customer submitted a UPI UTR, click **Approve** in the pending queue.
     - If a customer paid via NEFT/IMPS/Cash, click **Record Offline Credit / Bank Transfer**, pick the customer's email, enter the ₹ amount and reference note, and submit — their wallet is credited immediately with a receipt voucher.
3. **Minutes 10–12 — Book Carrier AWB & 1-Box Price Override (`Orders ▸ Shipment Detail`):**
   - Open any order (`/shipments/[id]` or `/b2b/shipments/[id]`):
     - In **Carrier Booking & Bill**, record or book the Delhivery AWB and actual carrier charge.
     - In **Override / Adjust Shipment Price**, type the **New Final Price (incl. GST) ₹** and a short reason:
       - Lower price → customer's wallet is **refunded automatically** + **GST Credit Note** issued.
       - Higher price → customer's wallet is **debited automatically** + **GST Debit Note** issued.
4. **Minutes 13–15 — Hub Weight Audit & Field OTP Delivery (`Ops Control Tower` `/ops`):**
   - Open **Ops Control Tower (`/ops`)**:
     - **First-Mile Pickups tab:** Confirm picked box counts on scheduled `PURs` and print the Manifest Run-Sheet.
     - **Hub Weight Audit (`Record Measurement`):** Enter measured weight/dimensions (and optional `Override Final Price ₹`) — Logismart automatically reprices the shipment, settles the wallet difference, logs a Weight Mismatch row, and issues the GST Note.
     - **Last-Mile Deliveries tab:** Switch to **Field Executive App (Mobile POD & Pickup)** view to see how riders mark parcels `Out for Delivery`, verify the consignee's **6-digit OTP**, and log COD cash collection.
