// frontend/src/lib/legal.ts
/**
 * Shared constants and helpers for the public legal pages (C-08):
 * Terms of Service & Carriage, Privacy Policy, Refund & Cancellation Policy
 * and Grievance Redressal.
 *
 * The page TEXT is an Indian-courier MVP draft that still needs legal review;
 * every page shows `LEGAL_DRAFT_BANNER_TEXT` until counsel signs it off.
 *
 * Spring Boot analogy: a small `@ConfigurationProperties` holder plus a pure
 * mapper (`TenantSettings` -> view model) used by several controllers.
 */
import type { GrievanceOfficerSettings, TenantSettings } from "@/types/tenant";

/** Tenant-relative paths of the legal pages (pass through `routeTo()`). */
export const LEGAL_PATHS = {
  terms: "/terms",
  privacy: "/privacy",
  refund: "/refund-policy",
  prohibited: "/prohibited-items",
  grievance: "/grievance",
} as const;

/**
 * Items that may never be shipped (Terms §4 and `/prohibited-items`). Mirrors
 * Delhivery One's restricted-items list (help.delhivery.com/docs/restricted-items):
 * goods that pose a health, safety, property or environment risk.
 */
export const PROHIBITED_ITEMS: ReadonlyArray<string> = [
  "Explosives, fireworks, ammunition, firearms and their parts",
  "Flammable liquids or solids, compressed gases, aerosols, paints and solvents",
  "Corrosive, toxic, radioactive or infectious substances; hazardous chemicals",
  "Loose lithium batteries and power banks shipped on their own",
  "Narcotics, psychotropic substances and drug paraphernalia",
  "Currency, coins, bullion, cheques, bearer instruments, lottery tickets",
  "Precious metals, jewellery and precious or semi-precious stones",
  "Live animals, plants, seeds, human or animal remains",
  "Perishable food that needs temperature control",
  "Counterfeit, pirated or obscene goods, and anything banned by Indian law",
  "Any item the carrier partner lists as restricted for its network",
];

/** Display date of the current draft (the backend stamps `TERMS_VERSION` at signup). */
export const LEGAL_LAST_UPDATED = "30 October 2026";

/** Visible banner text shown on every legal page until counsel approves it. */
export const LEGAL_DRAFT_BANNER_TEXT = "Draft — needs legal review";

/**
 * Standard draft liability cap per shipment (`min(declared_value, ₹5,000)`, G-05).
 * Delhivery One (`resolving-claims`, `lost-and-damage-claims-b2b-1`, `protect`)
 * settles claims up to the shipment's standard/Protect coverage limit; counsel
 * must confirm this figure before go-live.
 */
export const DRAFT_LIABILITY_CAP_INR = "₹5,000";

/** Shown when the tenant has not configured a grievance officer field yet. */
export const GRIEVANCE_FIELD_FALLBACK = "To be announced";

/** Platform name used when the tenant name is missing. */
const DEFAULT_TENANT_NAME = "Naviera";

/** Grievance officer details ready for display (every field is a non-empty string). */
export interface GrievanceOfficerDisplay {
  name: string;
  email: string;
  phone: string;
  /** True when at least one real contact channel (email or phone) is configured. */
  isConfigured: boolean;
}

/**
 * Returns a trimmed string, or null when the value is blank / not a string.
 *
 * @param value - Raw value read from the tenant settings JSON.
 * @returns The trimmed text, or null.
 */
function _cleanText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/**
 * Resolves the grievance officer from `settings.contact.grievance_officer`
 * (public, tenant-editable), falling back to "To be announced" per field.
 *
 * @param settings - Public tenant settings (may be undefined on a cold page).
 * @returns Display-ready officer details.
 */
export function resolveGrievanceOfficer(
  settings: TenantSettings | undefined | null
): GrievanceOfficerDisplay {
  const officer: GrievanceOfficerSettings | undefined =
    settings?.contact?.grievance_officer;
  const email = _cleanText(officer?.email);
  const phone = _cleanText(officer?.phone);
  return {
    name: _cleanText(officer?.name) ?? GRIEVANCE_FIELD_FALLBACK,
    email: email ?? GRIEVANCE_FIELD_FALLBACK,
    phone: phone ?? GRIEVANCE_FIELD_FALLBACK,
    isConfigured: Boolean(email || phone),
  };
}

/**
 * The tenant's display name for legal text ("Logismart"), or the platform name.
 *
 * @param name - `tenant.name` from the public tenant config.
 * @returns A non-empty display name.
 */
export function legalEntityName(name: string | undefined | null): string {
  return _cleanText(name) ?? DEFAULT_TENANT_NAME;
}
