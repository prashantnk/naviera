// frontend/src/app/[tenant_slug]/(marketing)/page.tsx
import { FeaturesSection } from "@/components/blocks/features-section";
import { HeroSection } from "@/components/blocks/hero-section";
import { getTenantBySlug } from "@/lib/api";
import { PageBlock } from "@/types/tenant";

export default async function MarketingPage({ params }: { params: Promise<{ tenant_slug: string }> }) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);

  if (!tenant || !tenant.settings?.landing_page) return null;

  const { blocks } = tenant.settings.landing_page;

  return (
    <main className="flex-1 flex flex-col">
      {/* 1. Render Dynamic Database Blocks */}
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
                trustPartners={block.content.trustPartners}
                layoutVariant={block.content.layoutVariant}
                images={block.content.images}
              />
            );
          default:
            return null;
        }
      })}

      {/* 2. 🔥 RESTORED: The Features Section */}
      <FeaturesSection tenantName={tenant.name} />
    </main>
  );
}