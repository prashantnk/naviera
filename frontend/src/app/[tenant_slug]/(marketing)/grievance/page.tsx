// frontend/src/app/[tenant_slug]/(marketing)/grievance/page.tsx
//
// Grievance Redressal (C-08). Officer name/email/phone come from the tenant's
// public settings (`settings.contact.grievance_officer`), falling back to
// "To be announced". Timelines follow the Consumer Protection (E-Commerce)
// Rules 2020 (acknowledge in 48 h, resolve within one month) and SPDI Rule 5(9).
import { LegalList, LegalPage, LegalSection } from "@/components/blocks/legal-page";
import { getTenantBySlug } from "@/lib/api";
import { legalEntityName, resolveGrievanceOfficer } from "@/lib/legal";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Grievance Officer" };

export default async function GrievancePage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const name = legalEntityName(tenant?.name);
  const officer = resolveGrievanceOfficer(tenant?.settings);
  const supportEmails = tenant?.settings?.contact?.emails ?? [];
  const supportPhones = tenant?.settings?.contact?.phones ?? [];

  return (
    <LegalPage title="Grievance Officer" tenantName={name}>
      <LegalSection id="officer" title="1. Contact the Grievance Officer">
        <p>
          Complaints about our service, a shipment, a refund or your personal
          data can be sent to {name}&apos;s Grievance Officer:
        </p>
        <dl
          data-testid="grievance.officer"
          className="grid grid-cols-1 sm:grid-cols-[8rem_1fr] gap-x-4 gap-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <dt className="font-semibold text-slate-900">Name</dt>
          <dd>{officer.name}</dd>
          <dt className="font-semibold text-slate-900">Email</dt>
          <dd className="break-all">{officer.email}</dd>
          <dt className="font-semibold text-slate-900">Phone</dt>
          <dd>{officer.phone}</dd>
        </dl>
        {!officer.isConfigured &&
          (supportEmails.length > 0 || supportPhones.length > 0) && (
            <p data-testid="grievance.support-fallback">
              Until the officer&apos;s details are published, please write to our
              support team at {[...supportEmails, ...supportPhones].join(" / ")}.
            </p>
          )}
      </LegalSection>

      <LegalSection id="how" title="2. What to include">
        <LegalList
          items={[
            "your name, registered email or phone number;",
            "the tracking ID (AWB / LR number) or support ticket number, if any;",
            "what went wrong and what you want us to do, with photos or documents.",
          ]}
        />
      </LegalSection>

      <LegalSection id="timelines" title="3. Our timelines">
        <LegalList
          items={[
            "We acknowledge every complaint within 48 hours.",
            "We aim to resolve it within one month of receiving it, and tell you the outcome in writing.",
          ]}
        />
        <p>
          If you are not satisfied, you may approach the consumer commission
          (consumer helpline 1915 / consumerhelpline.gov.in) or, for personal
          data, the Data Protection Board of India.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
