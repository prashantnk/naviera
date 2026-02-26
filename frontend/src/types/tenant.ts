// src/types/tenant.ts

// 1. The specific content inside a Hero block
export interface HeroBlockContent {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
}

// 2. A generic block on the page. 
// As we add features (like a Trust Bar or Pricing), we will expand this union type.
export interface PageBlock {
  type: "HERO" | "FEATURES" | "TRUST_BAR";
  content: HeroBlockContent; // Will become a Union type later as we add more blocks
}

// 3. The settings JSON object that lives inside the DB
export interface TenantSettings {
  brand?: {
    primary_color: string;
  };
  landing_page?: {
    blocks: PageBlock[];
  };
}

// 4. The Master Tenant Model (Mirrors TenantRead in FastAPI)
export interface Tenant {
  id: string;
  name: string;
  slug: string;
  settings: TenantSettings;
}