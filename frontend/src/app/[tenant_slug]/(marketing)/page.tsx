// frontend/src/app/[tenant_slug]/(marketing)/page.tsx
import { FeaturesSection } from "@/components/blocks/features-section";
import { HeroSection } from "@/components/blocks/hero-section";
import { getTenantBySlug } from "@/lib/api";
import { FeaturesBlockContent, HeroBlockContent, PageBlock } from "@/types/tenant";

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
            const content: HeroBlockContent = block.content as HeroBlockContent; // Type assertion for safety
            return (
              <HeroSection
                key={index}
                title={content.title}
                subtitle={content.subtitle}
                ctaText={content.ctaText}
                ctaLink={content.ctaLink}
                badge={content.badge}
                trustPartners={content.trustPartners}
                layoutVariant={content.layoutVariant}
                images={content.images}
              />
            );
          // 🔥 NEW: Map the features block
          case "FEATURES":
            return <FeaturesSection key={index} content={block.content as FeaturesBlockContent} />;
          default:
            return null;
        }
      })}
    </main>
  );
}