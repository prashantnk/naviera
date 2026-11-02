// frontend/src/app/[tenant_slug]/(marketing)/prohibited-items/page.tsx
//
// Prohibited & Restricted Items (C-08). Linked from the signup consent
// ("will not ship prohibited items"), the footer and Terms §4. Mirrors
// Delhivery One's "Restricted Items" article (help.delhivery.com/docs/restricted-items):
// dangerous goods are not moved on the network, and shipping them may lead to
// seizure, disposal and penalties for the seller. Draft pending legal review.
import { LegalList, LegalPage, LegalSection } from "@/components/blocks/legal-page";
import { TenantLink } from "@/components/blocks/tenant-link";
import { getTenantBySlug } from "@/lib/api";
import { LEGAL_PATHS, PROHIBITED_ITEMS, legalEntityName } from "@/lib/legal";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Prohibited & Restricted Items" };

export default async function ProhibitedItemsPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const name = legalEntityName(tenant?.name);

  return (
    <LegalPage title="Prohibited & Restricted Items" tenantName={name}>
      <LegalSection id="why" title="1. Why some items cannot be shipped">
        <p>
          Dangerous or restricted goods put people, property and the environment
          at risk while they move through sorting hubs, trucks and aircraft. To
          keep the network safe and legal, {name} and its carrier partners do
          not accept them, whatever the packaging or declared value.
        </p>
      </LegalSection>

      <LegalSection id="list" title="2. Items you must not ship">
        <LegalList items={[...PROHIBITED_ITEMS]} />
      </LegalSection>

      <LegalSection id="consequences" title="3. What happens if a prohibited item is found">
        <p>
          The shipment may be held, returned at your cost, handed to the
          authorities or destroyed, and your account may be suspended. You bear
          every penalty, seizure, fine and loss that results, as set out in our{" "}
          <TenantLink href={LEGAL_PATHS.terms} className="text-primary underline">
            Terms of Service &amp; Carriage
          </TenantLink>
          . Freight for such shipments is not refunded.
        </p>
      </LegalSection>

      <LegalSection id="unsure" title="4. Not sure about an item?">
        <p>
          Ask us before you book. Contact support from the{" "}
          <TenantLink href="/contact" className="text-primary underline">
            Contact Us
          </TenantLink>{" "}
          page with a description of the item and we will confirm whether it
          can be shipped.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
