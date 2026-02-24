// src/app/(marketing)/page.tsx
import { HeroSection } from "@/components/blocks/hero-section";
import { APP_CONFIG } from "@/lib/config";

// --- MOCK DB RESPONSE ---
// Eventually, this will come from: await api.get(`/tenants/${subdomain}`)
const MOCK_TENANT_CONFIG = {
  name: "Naviera Logistics",
  blocks: [
    {
      type: "HERO",
      content: {
        title: "Modern Logistics for the Digital Age",
        subtitle: "Ship faster, track better, and scale your delivery operations with our multi-tenant SaaS platform.",
        ctaText: "Get Started",
        ctaLink: "/login",
        badge: "v1.0 Public Beta",
      },
    },
    // We can add "FEATURES", "PRICING" blocks here later
  ],
};

export default function MarketingPage() {
  const { blocks } = MOCK_TENANT_CONFIG;

  return (
    <main className="flex min-h-screen flex-col">
      {/* This is the "Page Builder" Loop 
        It iterates through the JSON config and picks the right component.
      */}
      {blocks.map((block, index) => {
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

      {/* Footer (Static for now) */}
      <footer className="py-6 text-center text-sm text-gray-500">
        Powered by {APP_CONFIG.name}
      </footer>
    </main>
  );
}