// src/app/[tenant_slug]/(app)/layout.tsx
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppHeader } from "@/components/blocks/app-header";
import { AppSidebar } from "@/components/blocks/app-sidebar";
import { TenantProvider } from "@/components/providers/tenant-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { getTenantBySlug } from "@/lib/api";
import { headers } from "next/headers";

export default async function AppLayout({
    children,
    params,
}: {
    children: React.ReactNode;
    params: Promise<{ tenant_slug: string }>;
}) {
    // 1. Fetch DB Configuration
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);
    const primaryColor = tenant?.settings?.brand?.primary_color;

    // 2. Extract Environment Routing Mode
    const headersList = await headers();
    const routingMode = (headersList.get("x-routing-mode") as "subdomain" | "path") || "path";

    return (
        <div className="min-h-screen bg-slate-50 flex">
            <ThemeProvider primaryColor={primaryColor} />

            <TenantProvider tenant={tenant} routingMode={routingMode}>
                {/* 3. The Security Gate */}
                <AuthGuard>

                    {/* 4. The UI Shell */}
                    <AppSidebar />

                    <div className="flex-1 flex flex-col min-w-0">
                        <AppHeader />
                        <main className="flex-1 p-6">
                            {children}
                        </main>
                    </div>

                </AuthGuard>
            </TenantProvider>
        </div>
    );
}