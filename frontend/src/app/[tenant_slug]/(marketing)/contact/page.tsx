// frontend/src/app/[tenant_slug]/(marketing)/contact/page.tsx
import { getTenantBySlug } from "@/lib/api";
import { Mail, MapPin, Phone } from "lucide-react";

export default async function ContactPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const contact = tenant?.settings?.contact;

  return (
    <div className="bg-slate-50 py-20">
      <div className="container mx-auto px-4 md:px-6 max-w-5xl">
        <div className="text-center mb-16">
          <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight">
            Contact {tenant?.name}
          </h1>
          <p className="text-lg text-slate-500 mt-4">
            We are here to help. Reach out to us through any of the channels
            below.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-16">
          {/* Contact Details Card */}
          <div className="bg-white p-8 rounded-3xl shadow-sm border border-slate-100 space-y-8">
            <div>
              <h3 className="text-xl font-bold text-slate-900 flex items-center gap-2 mb-4">
                <Phone className="text-primary" /> Phone Support
              </h3>
              <div className="space-y-3 text-slate-600">
                {/* 🔥 DYNAMIC TOLL FREE */}
                {contact?.toll_free && (
                  <a
                    href={`tel:${contact.toll_free.replace(/[^0-9+]/g, "")}`}
                    className="block font-semibold text-lg text-slate-900 hover:text-primary transition-colors w-fit"
                  >
                    Toll Free: {contact.toll_free}
                  </a>
                )}
                {/* 🔥 DYNAMIC REGULAR PHONES */}
                {contact?.phones?.map((p) => (
                  <a
                    key={p}
                    href={`tel:${p.replace(/[^0-9+]/g, "")}`}
                    className="block hover:text-primary transition-colors w-fit"
                  >
                    Call / WhatsApp: {p}
                  </a>
                ))}
              </div>
            </div>

            <div>
              <h3 className="text-xl font-bold text-slate-900 flex items-center gap-2 mb-4">
                <Mail className="text-primary" /> Email Support
              </h3>
              <div className="space-y-3 text-slate-600">
                {contact?.emails?.map((e) => (
                  <a
                    key={e}
                    href={`mailto:${e}`}
                    className="block hover:text-primary transition-colors w-fit"
                  >
                    {e}
                  </a>
                ))}
              </div>
            </div>

            <div>
              <h3 className="text-xl font-bold text-slate-900 flex items-center gap-2 mb-4">
                <MapPin className="text-primary" /> Corporate Hub
              </h3>
              {/* 🔥 DYNAMIC ADDRESS WITH LINE BREAKS */}
              <p className="text-slate-600 whitespace-pre-line leading-relaxed">
                {contact?.address || "Address not provided."}
              </p>
            </div>
          </div>

          {/* Escalation Matrix Card */}
          <div className="bg-slate-900 text-white p-8 rounded-3xl shadow-xl space-y-6">
            <h3 className="text-2xl font-bold border-b border-slate-700 pb-4">
              Escalation Matrix
            </h3>
            <p className="text-slate-400">
              If your issue is not resolved, please follow our escalation path
              for swift resolution.
            </p>

            <div className="space-y-6 pt-4">
              {tenant?.settings?.escalation_matrix?.map(
                (matrix, index, arr) => (
                  <div
                    key={index}
                    className={`bg-slate-800 p-4 rounded-xl ${
                      index === arr.length - 1 ? "border border-primary/30" : ""
                    }`}
                  >
                    <p className="text-primary font-bold uppercase tracking-wider text-sm mb-1">
                      {matrix.level}
                    </p>
                    <p className="font-medium">
                      Email:{" "}
                      <a
                        href={`mailto:${matrix.email}`}
                        className="hover:underline"
                      >
                        {matrix.email}
                      </a>
                    </p>
                  </div>
                )
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
