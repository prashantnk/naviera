// frontend/src/app/[tenant_slug]/layout.tsx
import { getTenantBySlug } from "@/lib/api";
import { Metadata } from "next";
import { notFound } from "next/navigation";
import { TenantProvider } from "@/components/providers/tenant-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { headers } from "next/headers";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}): Promise<Metadata> {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);

  const tenantName = tenant?.name || "Naviera";

  const firstBlockContent = tenant?.settings?.landing_page?.blocks[0]?.content;
  const subtitle =
    firstBlockContent && "subtitle" in firstBlockContent
      ? (firstBlockContent.subtitle as string)
      : null;
  const description = subtitle || "Enterprise Multi-Tenant Logistics.";

  const defaultFallbackIcon =
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232563eb' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z'/%3E%3Cpolyline points='3.29 7 12 12 20.71 7'/%3E%3Cline x1='12' y1='22' x2='12' y2='12'/%3E%3C/svg%3E";
  const logoUrl = tenant?.settings?.brand?.logo_url || defaultFallbackIcon;

  return {
    title: {
      template: `%s | ${tenantName}`,
      default: `${tenantName} | Logistics Portal`,
    },
    description,
    icons: {
      icon: [{ url: logoUrl, href: logoUrl }],
      shortcut: [{ url: logoUrl, href: logoUrl }],
      apple: [{ url: logoUrl, href: logoUrl }],
    },
  };
}

export default async function TenantRootLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;

  // 1. Fetch exactly ONCE
  const tenant = await getTenantBySlug(tenant_slug);

  // 2. Handle 404s globally
  if (!tenant) {
    notFound();
  }

  const primaryColor = tenant.settings?.brand?.primary_color;
  const secondaryColor = tenant.settings?.brand?.secondary_color;

  const headersList = await headers();
  const routingMode =
    (headersList.get("x-routing-mode") as "subdomain" | "path") || "path";

  // 3. Inject Providers globally
  return (
    <TenantProvider tenant={tenant} routingMode={routingMode}>
      <ThemeProvider
        primaryColor={primaryColor}
        secondaryColor={secondaryColor}
      />
      {children}
    </TenantProvider>
  );
}
