// frontend/src/app/[tenant_slug]/(marketing)/refund-policy/page.tsx
//
// Refund & Cancellation Policy (C-08). Cancellation rules mirror Delhivery One
// (help.delhivery.com/docs/cancel-forward-order: Ready to Ship / Ready for
// Pickup = immediate freight refund; In Transit = treated as RTO; Out for
// Delivery / Delivered = not cancellable) and weight-dispute refunds
// (help.delhivery.com/docs/weight-dispute). Draft pending legal review.
import { LegalList, LegalPage, LegalSection } from "@/components/blocks/legal-page";
import { TenantLink } from "@/components/blocks/tenant-link";
import { getTenantBySlug } from "@/lib/api";
import { LEGAL_PATHS, legalEntityName } from "@/lib/legal";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Refund & Cancellation Policy" };

/** Cancellation outcome per shipment stage (Delhivery One `cancel-forward-order`). */
const CANCELLATION_RULES: ReadonlyArray<{
  stage: string;
  canCancel: string;
  refund: string;
}> = [
  {
    stage: "Ready to Ship (booked, not yet in a pickup request)",
    canCancel: "Yes",
    refund: "Full freight refunded to your wallet immediately",
  },
  {
    stage: "Ready for Pickup (pickup scheduled, not yet picked up)",
    canCancel: "Yes",
    refund: "Full freight refunded to your wallet immediately",
  },
  {
    stage: "In Transit",
    canCancel: "Yes, as a return to origin (RTO)",
    refund: "No freight refund; RTO charges apply",
  },
  {
    stage: "Out for Delivery",
    canCancel: "No",
    refund: "The receiver can refuse the parcel; it then returns as RTO",
  },
  {
    stage: "Delivered",
    canCancel: "No",
    refund: "Book a reverse pickup (customer return) instead",
  },
];

export default async function RefundPolicyPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const name = legalEntityName(tenant?.name);

  return (
    <LegalPage title="Refund & Cancellation Policy" tenantName={name}>
      <LegalSection id="cancel" title="1. Cancelling a shipment">
        <p>
          Cancel a shipment from its details page. What happens depends on how
          far the shipment has moved:
        </p>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-900">
              <tr>
                <th scope="col" className="p-3 font-semibold">Shipment stage</th>
                <th scope="col" className="p-3 font-semibold">Can I cancel?</th>
                <th scope="col" className="p-3 font-semibold">Freight refund</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {CANCELLATION_RULES.map((rule) => (
                <tr key={rule.stage}>
                  <td className="p-3">{rule.stage}</td>
                  <td className="p-3">{rule.canCancel}</td>
                  <td className="p-3">{rule.refund}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>B2B Cargo (LTL/FTL) shipments follow the same stages.</p>
      </LegalSection>

      <LegalSection id="refunds" title="2. Other refunds and credits">
        <LegalList
          items={[
            "Weight disputes decided in your favour: the extra amount charged is credited back to your wallet.",
            "Approved loss or damage claims: credited to your wallet or issued as a credit note, as set out in our Terms.",
            "A wallet recharge that failed or was charged twice: refunded to the original payment method within 5–7 business days after we confirm it with the bank.",
            "Unused wallet balance when you close your account: refunded to your verified bank account within 15 business days, after deducting any dues.",
          ]}
        />
        <p>
          Refunds are never paid in cash. Freight is not refunded for shipments
          that were delivered, returned (RTO) or held because of prohibited or
          wrongly declared contents.
        </p>
      </LegalSection>

      <LegalSection id="cod" title="3. Cash on Delivery">
        <p>
          COD amounts collected from receivers belong to you and are remitted as
          described in our{" "}
          <TenantLink href={LEGAL_PATHS.terms} className="text-primary underline">
            Terms of Service &amp; Carriage
          </TenantLink>
          . Refunds to your buyers for goods are your responsibility as the
          seller.
        </p>
      </LegalSection>

      <LegalSection id="help" title="4. Need help?">
        <p>
          Raise a support ticket from your account, or contact our{" "}
          <TenantLink href={LEGAL_PATHS.grievance} className="text-primary underline">
            Grievance Officer
          </TenantLink>{" "}
          if a refund is not resolved.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
