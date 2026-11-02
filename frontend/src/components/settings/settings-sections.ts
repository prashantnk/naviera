// frontend/src/components/settings/settings-sections.ts
/**
 * Which Settings section (left menu) holds each top-level form field, so a failed
 * save can open the section with the first error instead of leaving the admin on a
 * section whose fields all look fine.
 */

/** Left-menu sections of the Settings page. */
export type SettingsSectionId = "company" | "branding" | "website" | "support" | "wallet" | "rates";

/** Top-level form key → section that renders it. */
const SECTION_BY_FIELD: Readonly<Record<string, SettingsSectionId>> = {
  company: "company",
  brand: "branding",
  announcement_bar: "website",
  hero_block: "website",
  features_block: "website",
  about_page: "website",
  services_page: "website",
  contact: "support",
  support: "support",
  socials: "support",
  escalation_matrix: "support",
  wallet_config: "wallet",
};

/**
 * The section to open for a set of validation errors.
 *
 * @param errorKeys - Top-level keys of react-hook-form's `errors` object, in form order.
 * @returns The section of the first key that maps to one, or null when none does.
 */
export function sectionForErrors(errorKeys: readonly string[]): SettingsSectionId | null {
  for (const key of errorKeys) {
    const section = SECTION_BY_FIELD[key];
    if (section) return section;
  }
  return null;
}

/** Display names, used in the "fix the errors" toast. */
export const SECTION_LABELS: Readonly<Record<SettingsSectionId, string>> = {
  company: "Company Profile",
  branding: "Branding & Theme",
  website: "Website Content",
  support: "Support & Escalation",
  wallet: "Wallet & Payments",
  rates: "Pricing",
};
