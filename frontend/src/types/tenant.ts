// frontend/src/types/tenant.ts

export interface HeroBlockContent {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
  trustPartners?: string[];
  // 🔥 NEW: Data-driven UI controls for the Hero
  layoutVariant?: "saas" | "logistics_bento";
  images?: string[];
}

export interface PageBlock {
  type: "HERO" | "FEATURES" | "TRUST_BAR";
  content: HeroBlockContent;
}

export interface TenantSettings {
  brand?: {
    primary_color: string;
    secondary_color?: string; // 🔥 NEW: For Logismart's Navy Blue
    logo_url?: string;
  };
  // 🔥 NEW: Controls the top header bar dynamically
  announcement_bar?: {
    is_active: boolean;
    text: string;
  };
  contact?: {
    phones?: string[];
    emails?: string[];
    whatsapp?: string;
    socials?: {
      facebook?: string;
      instagram?: string;
      linkedin?: string;
      youtube?: string;
    };
  };
  landing_page?: {
    blocks: PageBlock[];
  };
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  settings: TenantSettings;
}
