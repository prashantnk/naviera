// src/app/[tenant_slug]/(marketing)/page.tsx
import { HeroSection } from "@/components/blocks/hero-section";
import { getTenantBySlug } from "@/lib/api";
import { PageBlock } from "@/types/tenant";

export default async function MarketingPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);
  
  if (!tenant || !tenant.settings?.landing_page) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center p-20 text-center">
        <h1 className="text-2xl font-bold text-red-500">Tenant Not Found</h1>
        <p className="text-gray-500">Could not find configuration for: {tenant_slug}</p>
      </div>
    );
  }

  const { blocks } = tenant.settings.landing_page;

  // Notice we removed the <main> and <footer> tags here! 
  // The layout.tsx handles them now. We just return the specific blocks.
  return (
    <>
      {blocks.map((block: PageBlock, index: number) => {
        switch (block.type) {
          case "HERO":
            return (
              <HeroSection
                key={index}
                title={block.content.title}
                subtitle={block.content.subtitle}
                ctaText={block.content.ctaText}
                ctaLink={block.content.ctaLink}
                badge={block.content.badge}
              />
            );
          default:
            return null;
        }
      })}
    </>
  );
}