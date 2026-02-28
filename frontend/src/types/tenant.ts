// frontend/src/types/tenant.ts

export interface HeroBlockContent {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
  trustPartners?: string[];
  layoutVariant?: "saas" | "logistics_bento";
  images?: string[];
}

export interface ClientLogo {
  name: string;
  color: string; // Dynamic hex code for the brand
}

// 🔥 NEW: Structure for the Features Section
export interface FeatureItem {
  title: string;
  description: string;
  icon: string;
  bullets?: string[];
}

export interface FeaturesBlockContent {
  badge?: string;
  headline: string;
  subheadline?: string;
  features: FeatureItem[];
  clientsHeadline?: string;
  clientsSubheadline?: string;
  clientLogos?: ClientLogo[];
}

export interface PageBlock {
  type: "HERO" | "FEATURES" | "TRUST_BAR";
  content: HeroBlockContent | FeaturesBlockContent | object;
}

export interface TenantSettings {
  brand?: {
    primary_color: string;
    secondary_color?: string;
    logo_url?: string;
  };
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
