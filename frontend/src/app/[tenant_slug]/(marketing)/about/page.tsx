// frontend/src/app/[tenant_slug]/(marketing)/about/page.tsx
import { getTenantBySlug } from "@/lib/api";

export default async function AboutPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);

  // Fallback in case DB is missing
  const config = tenant?.settings?.about_page;
  if (!config)
    return (
      <div className="py-20 text-center">About content coming soon...</div>
    );

  return (
    <div className="bg-slate-50 min-h-screen py-16">
      <div className="container mx-auto px-4 md:px-6 max-w-4xl space-y-16 bg-white p-8 md:p-16 rounded-3xl shadow-sm border border-slate-100">
        <section className="space-y-6 text-slate-600 leading-relaxed text-lg">
          <h1 className="text-4xl font-extrabold text-slate-900 text-center mb-8">
            {config.headline}
          </h1>
          {config.paragraphs.map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </section>

        <section className="space-y-6">
          <h2 className="text-3xl font-bold text-slate-900 text-center mb-8">
            {config.offersHeadline}
          </h2>
          <ul className="space-y-6 text-lg text-slate-600">
            {config.offers.map((offer, i) => (
              <li key={i}>
                <strong className="text-slate-900">{offer.title}:</strong>{" "}
                {offer.description}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
