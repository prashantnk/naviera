// frontend/src/app/[tenant_slug]/(marketing)/layout.tsx
import { Footer } from "@/components/blocks/footer";
import { Header } from "@/components/blocks/header";
import { TenantProvider } from "@/components/providers/tenant-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { getTenantBySlug } from "@/lib/api";
import { MessageCircle } from "lucide-react";
import { headers } from "next/headers";
import Link from "next/link";

export default async function MarketingLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);

  // Extract theme and contact info from the DB
  const primaryColor = tenant?.settings?.brand?.primary_color;
  const secondaryColor = tenant?.settings?.brand?.secondary_color;
  const whatsappNumber = tenant?.settings?.contact?.whatsapp;

  // Next 15: Await the headers API to extract our middleware injection
  const headersList = await headers();
  const routingMode = (headersList.get("x-routing-mode") as "subdomain" | "path") || "path";

  return (
    <div className="flex min-h-screen flex-col relative">
      <ThemeProvider primaryColor={primaryColor} secondaryColor={secondaryColor} />
      <TenantProvider tenant={tenant} routingMode={routingMode}>

        {/* Global Header */}
        <Header />

        {/* Main Page Content */}
        <div className="flex-1 bg-white">{children}</div>

        {/* 🔥 GLOBAL FOOTER ADDED HERE */}
        <Footer />

        {/* 🔥 GLOBAL FLOATING WHATSAPP BUTTON ADDED HERE */}
        {whatsappNumber && (
          <Link
            href={`https://wa.me/${whatsappNumber}`}
            target="_blank"
            className="fixed bottom-6 right-6 z-50 bg-[#25D366] text-white p-4 rounded-full shadow-2xl hover:scale-110 transition-transform flex flex-col items-center justify-center group"
          >
            <MessageCircle className="h-8 w-8" />
            <span className="absolute -top-8 right-0 bg-white text-slate-900 text-xs font-bold px-2 py-1 rounded shadow-md opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
              Chat With Us
            </span>
          </Link>
        )}

      </TenantProvider>
    </div>
  );
}