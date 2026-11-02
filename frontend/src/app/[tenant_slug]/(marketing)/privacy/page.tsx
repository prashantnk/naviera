// frontend/src/app/[tenant_slug]/(marketing)/privacy/page.tsx
//
// Privacy Policy (C-08). MVP draft covering the IT Act 2000 + SPDI Rules 2011
// (Rule 4 privacy policy, Rule 5 collection/grievance) and the basics of the
// Digital Personal Data Protection Act 2023 (notice, consent, purposes, rights,
// grievance). Counsel must review before go-live.
import { LegalList, LegalPage, LegalSection } from "@/components/blocks/legal-page";
import { TenantLink } from "@/components/blocks/tenant-link";
import { getTenantBySlug } from "@/lib/api";
import { LEGAL_PATHS, legalEntityName } from "@/lib/legal";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy Policy" };

export default async function PrivacyPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const name = legalEntityName(tenant?.name);

  return (
    <LegalPage title="Privacy Policy" tenantName={name}>
      <LegalSection id="scope" title="1. Scope">
        <p>
          This policy explains how {name} (&quot;we&quot;) collects, uses, shares
          and protects personal data when you use our website and shipping
          portal. It is published under the Information Technology Act, 2000 and
          the Information Technology (Reasonable Security Practices and
          Procedures and Sensitive Personal Data or Information) Rules, 2011, and
          follows the Digital Personal Data Protection Act, 2023 (&quot;DPDP
          Act&quot;). For the DPDP Act, {name} is the Data Fiduciary for your
          account data.
        </p>
      </LegalSection>

      <LegalSection id="data" title="2. What we collect">
        <LegalList
          items={[
            "Account data: name, email, phone number, password (stored only as a one-way hash), and your role in the workspace.",
            "Shipment data: pickup and delivery addresses, receiver name and phone, contents, declared value, invoices, weights, dimensions, photos and proof-of-delivery details (receiver name, delivery OTP status).",
            "Business / KYC data (B2B and COD sellers): company name, GSTIN, PAN, billing address and bank account details for COD remittance. Bank details and passwords are sensitive personal data under the SPDI Rules.",
            "Payment data: wallet recharges, UPI transaction references (UTR) and invoices. We do not store card numbers or UPI PINs.",
            "Technical data: IP address, browser type, pages visited, and the login token kept in your browser's local storage so you stay signed in.",
          ]}
        />
      </LegalSection>

      <LegalSection id="purpose" title="3. Why we use it">
        <LegalList
          items={[
            "to create and secure your account and verify your identity;",
            "to book, pick up, transport, track and deliver shipments, handle failed deliveries and returns;",
            "to calculate charges, debit your wallet, remit COD, raise GST invoices and keep tax records;",
            "to resolve support tickets, weight disputes and claims, and send service messages (booking, tracking, OTP);",
            "to prevent fraud and misuse, and to comply with law and lawful requests from authorities.",
          ]}
        />
        <p>
          We use personal data only for these purposes, on the basis of your
          consent (given when you create an account) or where the law allows it
          without consent (for example, legal and tax obligations).
        </p>
      </LegalSection>

      <LegalSection id="receivers" title="4. Data about your receivers">
        <p>
          When you book a shipment you give us your receiver&apos;s name, address
          and phone number. You confirm you are allowed to share them with us for
          delivering the parcel. Receivers can contact our Grievance Officer
          about their data at any time.
        </p>
      </LegalSection>

      <LegalSection id="sharing" title="5. Who we share it with">
        <LegalList
          items={[
            "Carrier and delivery partners, only the details needed to pick up and deliver the shipment (addresses, phone numbers, package details, COD amount).",
            "Service providers who host or run the platform for us (cloud hosting, database, authentication, email/SMS) under confidentiality obligations.",
            "Banks and payment providers, to process recharges, refunds and COD remittances.",
            "Government or law-enforcement authorities when the law requires it.",
          ]}
        />
        <p>We do not sell personal data.</p>
      </LegalSection>

      <LegalSection id="retention" title="6. How long we keep it">
        <p>
          We keep account data while your account is active. Shipment, invoice
          and payment records are kept for as long as tax and accounting laws
          require (generally 8 years under GST law). When data is no longer
          needed we delete or anonymise it.
        </p>
      </LegalSection>

      <LegalSection id="security" title="7. How we protect it">
        <p>
          We use reasonable security practices: encrypted connections (HTTPS),
          hashed passwords, access limited by role, and data separated per
          workspace. No system is perfectly secure; if a personal data breach
          affects you, we will inform you and the authorities as the law requires.
        </p>
      </LegalSection>

      <LegalSection id="rights" title="8. Your rights">
        <LegalList
          items={[
            "See a summary of the personal data we hold about you and how we use it.",
            "Correct or update inaccurate data (most of it from your Profile page).",
            "Ask us to erase data we no longer need, subject to legal retention.",
            "Withdraw consent. This stops future processing but may mean we can no longer provide the Service; it does not affect shipments already booked.",
            "Nominate a person to exercise these rights if you die or become unable to.",
            "Complain to our Grievance Officer, and if unresolved, to the Data Protection Board of India.",
          ]}
        />
      </LegalSection>

      <LegalSection id="children" title="9. Children">
        <p>
          The Service is meant for businesses and adults. We do not knowingly
          create accounts for anyone under 18.
        </p>
      </LegalSection>

      <LegalSection id="contact" title="10. Contact and changes">
        <p>
          Questions or requests about your data go to our{" "}
          <TenantLink href={LEGAL_PATHS.grievance} className="text-primary underline">
            Grievance Officer
          </TenantLink>
          . We may update this policy; the &quot;Last updated&quot; date above
          shows the current version.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
