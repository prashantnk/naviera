// frontend/src/types/tenant.ts

export interface HeroBlockContent {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
  trustPartners?: string[]; // e.g., ["DHL", "FedEx", "DTDC"]
}

export interface PageBlock {
  type: "HERO" | "FEATURES" | "TRUST_BAR";
  content: HeroBlockContent;
}

export interface TenantSettings {
  brand?: {
    primary_color: string;
    logo_url?: string; // Optional logo image
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
