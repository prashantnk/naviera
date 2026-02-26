// src/app/[tenant_slug]/(auth)/layout.tsx
import { TenantProvider } from "@/components/providers/tenant-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { getTenantBySlug } from "@/lib/api";
import { headers } from "next/headers";

export default async function AuthLayout({
    children,
    params,
}: {
    children: React.ReactNode;
    params: Promise<{ tenant_slug: string }>;
}) {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);
    const primaryColor = tenant?.settings?.brand?.primary_color;

    const headersList = await headers();
    const routingMode = (headersList.get("x-routing-mode") as "subdomain" | "path") || "path";

    return (
        <div className="min-h-screen bg-slate-50 flex flex-col">
            <ThemeProvider primaryColor={primaryColor} />
            <TenantProvider tenant={tenant} routingMode={routingMode}>
                <main className="flex-1 flex items-center justify-center p-4">
                    {children}
                </main>
            </TenantProvider>
        </div>
    );
}