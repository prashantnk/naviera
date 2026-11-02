// frontend/src/components/blocks/legal-page.tsx
import { LEGAL_DRAFT_BANNER_TEXT, LEGAL_LAST_UPDATED } from "@/lib/legal";
import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Shared shell for the public legal pages (Terms, Privacy, Refunds, Grievance).
 *
 * Renders the page title, the "last updated" line and the mandatory
 * "Draft — needs legal review" banner above the policy body. It is a plain
 * Server Component (no hooks), so the pages stay SEO-friendly.
 */
export function LegalPage({
  title,
  tenantName,
  children,
}: {
  title: string;
  tenantName: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-slate-50 min-h-screen py-12 md:py-16">
      <article className="container mx-auto px-4 md:px-6 max-w-4xl bg-white p-6 md:p-12 rounded-3xl shadow-sm border border-slate-100 space-y-8">
        <div
          role="note"
          data-testid="legal.draft-banner"
          className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-900"
        >
          <TriangleAlert className="h-5 w-5 shrink-0 mt-0.5" aria-hidden="true" />
          <div className="space-y-1 text-sm">
            <p className="font-bold">{LEGAL_DRAFT_BANNER_TEXT}</p>
            <p>
              This is a working draft published so customers can see the rules
              that apply today. It will be replaced by a lawyer-reviewed version.
            </p>
          </div>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight">
            {title}
          </h1>
          <p className="text-sm text-slate-500">
            {tenantName} · Last updated: {LEGAL_LAST_UPDATED}
          </p>
        </header>

        <div className="space-y-8 text-slate-700 leading-relaxed">{children}</div>
      </article>
    </div>
  );
}

/** One numbered policy section with a heading. */
export function LegalSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="space-y-3 scroll-mt-24">
      <h2 className="text-xl font-bold text-slate-900">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

/** Bulleted list used inside policy sections. */
export function LegalList({ items }: { items: ReactNode[] }) {
  return (
    <ul className="list-disc pl-6 space-y-1.5">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}
