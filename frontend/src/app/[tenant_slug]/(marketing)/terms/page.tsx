// frontend/src/app/[tenant_slug]/(marketing)/terms/page.tsx
//
// Terms of Service & Carriage (C-08). MVP draft for an Indian courier
// aggregator; mirrors Delhivery One rules where they apply. Sources
// (help.delhivery.com/docs/<slug>): restricted-items, calculating-volumetric-weight,
// weight-dispute, cod-remittance, cancel-forward-order, courier-returnrto,
// resolving-claims (B2C 72 h claim window), lost-and-damage-claims-b2b-1
// (B2B Cargo 5-day claim window).
import { LegalList, LegalPage, LegalSection } from "@/components/blocks/legal-page";
import { TenantLink } from "@/components/blocks/tenant-link";
import { getTenantBySlug } from "@/lib/api";
import {
  DRAFT_LIABILITY_CAP_INR,
  LEGAL_PATHS,
  PROHIBITED_ITEMS,
  legalEntityName,
} from "@/lib/legal";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms of Service & Carriage" };

/** Delivery attempts before a shipment is returned (matches `MAX_NDR_ATTEMPTS`). */
const MAX_DELIVERY_ATTEMPTS = 3;

export default async function TermsPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const name = legalEntityName(tenant?.name);

  return (
    <LegalPage title="Terms of Service & Carriage" tenantName={name}>
      <LegalSection id="acceptance" title="1. Who we are and acceptance">
        <p>
          These terms apply to every account, booking and shipment made through
          the {name} shipping portal (the &quot;Service&quot;). {name}{" "}
          (&quot;we&quot;, &quot;us&quot;) arranges pickup, transport and delivery
          of your shipments through its own network and carrier partners. By
          creating an account, booking a shipment or handing over a parcel you
          (&quot;shipper&quot;) agree to these terms, our{" "}
          <TenantLink href={LEGAL_PATHS.privacy} className="text-primary underline">
            Privacy Policy
          </TenantLink>{" "}
          and our{" "}
          <TenantLink href={LEGAL_PATHS.refund} className="text-primary underline">
            Refund &amp; Cancellation Policy
          </TenantLink>
          .
        </p>
      </LegalSection>

      <LegalSection id="account" title="2. Your account">
        <LegalList
          items={[
            "Give true, complete details (name, phone, email, pickup addresses). Business (B2B) accounts must also give valid GSTIN / PAN and bank details for KYC.",
            "Keep your password private. You are responsible for every booking made from your account.",
            "We may suspend an account that breaks these terms, ships prohibited items, or has unpaid dues.",
          ]}
        />
      </LegalSection>

      <LegalSection id="booking" title="3. Booking and declaring a shipment">
        <p>For every shipment you must declare correctly:</p>
        <LegalList
          items={[
            "the contents, their value (with a GST invoice where the law requires one, e.g. an e-way bill for consignments above ₹50,000);",
            "the dead weight and the box dimensions (length × breadth × height in cm);",
            "complete pickup and delivery addresses with a valid 6-digit PIN code and phone number.",
          ]}
        />
        <p>
          Pack every item securely so it survives normal handling, and stick the
          shipping label on the outside. We may open and inspect a shipment where
          the law or a carrier partner requires it, and we may refuse or hold any
          shipment we reasonably believe breaks these terms.
        </p>
      </LegalSection>

      <LegalSection id="prohibited" title="4. Prohibited and restricted items">
        <p>You must not ship any of the following:</p>
        <LegalList items={[...PROHIBITED_ITEMS]} />
        <p>
          How to check an item before you book is explained on our{" "}
          <TenantLink href={LEGAL_PATHS.prohibited} className="text-primary underline">
            Prohibited &amp; Restricted Items
          </TenantLink>{" "}
          page.
        </p>
        <p>
          If a prohibited item is found, the shipment may be held, returned at
          your cost, handed to the authorities or destroyed. You bear every
          penalty, seizure, fine and loss that results, and you indemnify us and
          our carrier partners against them.
        </p>
      </LegalSection>

      <LegalSection id="weight" title="5. Weight, volumetric weight and weight disputes">
        <LegalList
          items={[
            "You are charged on the chargeable weight: the higher of the dead weight and the volumetric weight. Volumetric weight = length × breadth × height (cm) ÷ 5000 for surface and express parcels, as applied by the carrier partner.",
            "The carrier partner may re-weigh and re-measure a shipment. If the measured chargeable weight is higher than declared, the difference (and any related RTO charge) is debited from your wallet or invoice; if it is lower, the difference is credited back.",
            "If you disagree with a re-measured weight, raise a weight dispute from the Disputes section within 7 days of it being shown, with photos of the packed box on a scale and with a tape across each side. Our decision after reviewing the carrier's evidence is final for that shipment.",
          ]}
        />
      </LegalSection>

      <LegalSection id="charges" title="6. Charges, wallet and payment">
        <LegalList
          items={[
            "The freight shown at booking includes GST and the surcharges listed on the booking screen. Final charges can change only for the reasons in these terms (weight, RTO, address change).",
            "Prepaid (B2C) bookings are paid from your wallet; a booking is accepted only when the wallet has enough balance. Business accounts may be invoiced as agreed with us.",
            "Return-to-origin (RTO) freight, and any charges levied by authorities, are payable by you.",
          ]}
        />
      </LegalSection>

      <LegalSection id="cod" title="7. Cash on Delivery (COD) and remittance">
        <LegalList
          items={[
            "For COD shipments the delivery agent collects the amount shown on the label from the receiver. A COD fee applies as shown at booking.",
            "Collected COD is remitted to the bank account verified on your account in the next remittance cycle after delivery is confirmed and the cash is deposited (target: within 7 days of delivery).",
            "We may set off unpaid freight, RTO, weight-dispute charges or a negative wallet balance against COD before remitting it. If your balance is negative, remittance waits until the next cycle.",
            "Report a missing or short remittance within 30 days of the delivery date.",
          ]}
        />
      </LegalSection>

      <LegalSection id="delivery" title="8. Delivery, failed delivery and return to origin">
        <p>
          We make up to {MAX_DELIVERY_ATTEMPTS} delivery attempts. If the receiver
          is unavailable, refuses the parcel or the address is wrong, the shipment
          is marked undelivered (NDR) and you can ask for a re-attempt, an
          address or phone update, or a return. After the last failed attempt the
          shipment is returned to the pickup address (RTO) and RTO freight is
          charged. Estimated delivery dates are estimates, not guarantees.
        </p>
      </LegalSection>

      <LegalSection id="cancellation" title="9. Cancellation">
        <p>
          You can cancel a shipment before it is picked up. Once it is in
          transit, a cancellation is treated as a return (RTO). Details and
          refunds are in our{" "}
          <TenantLink href={LEGAL_PATHS.refund} className="text-primary underline">
            Refund &amp; Cancellation Policy
          </TenantLink>
          .
        </p>
      </LegalSection>

      <LegalSection id="liability" title="10. Our liability">
        <LegalList
          items={[
            `For a shipment that is lost or damaged while in our or our carrier partner's custody, our liability is limited to the lower of (a) the declared value supported by your invoice and (b) ${DRAFT_LIABILITY_CAP_INR} per shipment (draft figure, to be confirmed), unless a higher cover was bought for that shipment.`,
            "We are not liable for indirect or consequential loss (loss of profit, business or market), for delay, or for loss caused by poor packing, wrong declaration, prohibited contents, or events beyond our reasonable control (natural disasters, strikes, government action).",
            "Freight charges are refunded only as set out in the Refund & Cancellation Policy.",
          ]}
        />
      </LegalSection>

      <LegalSection id="claims" title="11. Claims for loss, damage or missing items">
        <LegalList
          items={[
            "Damaged, missing or wrong items on a delivered parcel (B2C): raise a claim within 72 hours of delivery.",
            "B2B Cargo (LTL/FTL): raise damage, box-short or content-short claims within 5 days of delivery, and note any visible damage on the proof of delivery.",
            "Lost shipments: raise a claim once the shipment is confirmed lost by us.",
            "Attach at least 2 photos or 1 video of the box and the product with the AWB/LR number visible, the GST invoice, and (if you have it) a packing video. Claims are usually decided in 5–7 business days; approved amounts are credited to your wallet or issued as a credit note.",
          ]}
        />
      </LegalSection>

      <LegalSection id="law" title="12. Changes, governing law and grievances">
        <p>
          We may update these terms; the &quot;Last updated&quot; date above shows
          the current version, and continued use after an update means you
          accept it. These terms are governed by the laws of India, and the
          courts at the city of our registered office have exclusive
          jurisdiction. For complaints, contact our{" "}
          <TenantLink href={LEGAL_PATHS.grievance} className="text-primary underline">
            Grievance Officer
          </TenantLink>
          .
        </p>
      </LegalSection>
    </LegalPage>
  );
}
