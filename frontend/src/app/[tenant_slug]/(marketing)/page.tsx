// frontend/src/app/[tenant_slug]/(marketing)/page.tsx
import { FeaturesSection } from "@/components/blocks/features-section";
import { HeroSection } from "@/components/blocks/hero-section";
import { getTenantBySlug } from "@/lib/api";
import {
  FeaturesBlockContent,
  HeroBlockContent,
  PageBlock,
} from "@/types/tenant";

const DEFAULT_FEATURES_CONTENT: FeaturesBlockContent = {
  badge: "ENTERPRISE LOGISTICS PLATFORM",
  headline: "Complete Courier & Heavy Cargo Infrastructure",
  subheadline:
    "Unified B2C parcel express, B2B PTL/FTL lorry receipts, automated hub sortation, and GST-compliant billing.",
  features: [],
};

export default async function MarketingPage({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;
  const tenant = await getTenantBySlug(tenant_slug);

  if (!tenant || !tenant.settings?.landing_page) return null;

  const { blocks } = tenant.settings.landing_page;
  const hasFeaturesBlock = blocks.some(
    (block: PageBlock) => String(block.type).toUpperCase() === "FEATURES"
  );

  return (
    <main className="flex-1 flex flex-col">
      {blocks.map((block: PageBlock, index: number) => {
        const blockType = String(block.type).toUpperCase();
        switch (blockType) {
          case "HERO": {
            const content: HeroBlockContent = block.content as HeroBlockContent;
            return (
              <HeroSection
                key={index}
                title={content.title || tenant.name}
                subtitle={
                  content.subtitle ||
                  "Enterprise B2C Express & B2B Heavy Cargo Logistics."
                }
                ctaText={content.ctaText || "Book Your Shipment"}
                ctaLink={content.ctaLink || "/shipments/new"}
                badge={content.badge}
                trustPartners={content.trustPartners}
                layoutVariant={content.layoutVariant}
                images={content.images}
              />
            );
          }
          case "FEATURES":
            return (
              <FeaturesSection
                key={index}
                content={block.content as FeaturesBlockContent}
              />
            );
          default:
            return null;
        }
      })}
      {!hasFeaturesBlock && (
        <FeaturesSection content={DEFAULT_FEATURES_CONTENT} />
      )}
    </main>
  );
}
