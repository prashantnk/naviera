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
  phone?: string;
}

/** Grievance Officer contact, stored under `settings.contact` (public allow-list). */
export interface GrievanceOfficerSettings {
  name?: string;
  email?: string;
  phone?: string;
}

// Now add them to the main TenantSettings interface:
export interface TenantSettings {
  oAuthSignInEnabled?: boolean;
  brand?: {
    primary_color: string;
    secondary_color?: string;
    logo_url?: string;
    show_logo?: boolean;
  };
  announcement_bar?: {
    is_active: boolean;
    text: string;
  };
  contact?: {
    toll_free?: string;
    phones?: string[];
    emails?: string[];
    whatsapp?: string;
    address?: string;
    gstin?: string;
    socials?: {
      facebook?: string;
      instagram?: string;
      linkedin?: string;
      youtube?: string;
    };
    /** Grievance Officer shown on `/grievance` (IT Rules / Consumer Protection Rules). */
    grievance_officer?: GrievanceOfficerSettings;
  };
  support?: {
    help_center_url?: string;
  };
  landing_page?: {
    blocks: PageBlock[];
  };
  // THE NEW DB INJECTIONS
  about_page?: AboutPageConfig;
  services_page?: ServicesPageConfig;
  escalation_matrix?: EscalationLevel[];
  wallet_config?: {
    merchant_vpa?: string;
    merchant_name?: string;
    min_wallet_balance_b2c?: number;
    min_wallet_balance_b2b?: number;
    strict_finlock?: boolean;
    auto_detect_upi?: boolean;
    auto_detect_delay_seconds?: number;
    gstin?: string;
  };
  pricing_config?: {
    base_rate_per_kg?: number;
    b2b_docket_charge?: number;
    b2b_fov_percent?: number;
    fuel_surcharge_percent?: number;
    gst_tax_percent?: number;
    network_surcharge?: number;
    cod_fee_percent?: number;
  };
  gstin?: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  settings: TenantSettings;
}
