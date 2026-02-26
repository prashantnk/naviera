// src/app/[tenant_slug]/(marketing)/layout.tsx
import { Header } from "@/components/blocks/header";
import { TenantProvider } from "@/components/providers/tenant-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { getTenantBySlug } from "@/lib/api";
import { headers } from "next/headers";

export default async function MarketingLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  const primaryColor = tenant?.settings?.brand?.primary_color;

  // Next 15: Await the headers API to extract our middleware injection
  const headersList = await headers();
  const routingMode = (headersList.get("x-routing-mode") as "subdomain" | "path") || "path";

  return (
    <div className="flex min-h-screen flex-col">
      <ThemeProvider primaryColor={primaryColor} />
      {/* Pass the routingMode down! */}
      <TenantProvider tenant={tenant} routingMode={routingMode}>
        <Header />
        <div className="flex-1">{children}</div>
      </TenantProvider>
    </div>
  );
}