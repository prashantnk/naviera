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

// NEW: Structure for About Page
export interface AboutPageConfig {
  headline: string;
  paragraphs: string[];
  offersHeadline: string;
  offers: { title: string; description: string }[];
}

//  NEW: Structure for Services Page
export interface ServiceItem {
  title: string;
  description: string;
  icon: string;
}

export interface ServicesPageConfig {
  headline: string;
  description: string;
  services: ServiceItem[];
  valueAddHeadline: string;
  valueAddDescription: string;
  valueAdds: string[];
}

//  NEW: Structure for Contact Page Escalation
export interface EscalationLevel {
  level: string;
  email: string;
}

// Now add them to the main TenantSettings interface:
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
    toll_free?: string; // 🔥 NEW
    phones?: string[];
    emails?: string[];
    whatsapp?: string;
    address?: string; // 🔥 NEW
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
  // THE NEW DB INJECTIONS
  about_page?: AboutPageConfig;
  services_page?: ServicesPageConfig;
  escalation_matrix?: EscalationLevel[];
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  settings: TenantSettings;
}
