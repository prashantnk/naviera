// frontend/src/app/[tenant_slug]/layout.tsx
import { getTenantBySlug } from "@/lib/api";
import { Metadata } from "next";

export async function generateMetadata({ params }: { params: Promise<{ tenant_slug: string }> }): Promise<Metadata> {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);

    const tenantName = tenant?.name || "Logistics Solutions";
    const description = tenant?.settings?.landing_page?.blocks[0]?.content?.subtitle || "Fast, safe, and reliable delivery across the world.";

    return {
        // Next.js Title Template Feature
        // If a child page defines a title (e.g., "Dashboard"), it becomes "Dashboard | Logismart"
        // If it doesn't, it falls back to the default below.
        title: {
            template: `%s | ${tenantName}`,
            default: `${tenantName} | International & Domestic Courier`,
        },
        description,
    };
}

export default function TenantRootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    // This layout purely exists to inject metadata and pass children down
    // to the (app), (auth), and (marketing) route groups!
    return (<>{children}</>);
}