// frontend/src/components/settings/company-profile.ts
/**
 * Settings ▸ Company Profile: Logismart's own legal / GST identity (`settings.company`).
 *
 * The backend prints GST invoices, credit/debit notes and receipts from
 * `settings.company` FIRST (`resolve_supplier_gst_profile` in
 * backend/app/services/delhivery_modules.py) and only falls back to the legacy
 * `wallet_config.gstin`, `contact.gstin`, root `gstin` and `contact.address`. So the
 * editor must read and write `company.*`; the legacy GSTIN copies are kept equal so
 * every fallback reader agrees.
 *
 * `invoice_prefix` is shown read-only: it is locked once set (A4-33) and changing it
 * mid financial year would break the GST document series.
 *
 * Spring analogy: a mapper between the `@ConfigurationProperties` JSON and the form DTO.
 */

/** Editable Company Profile fields (form values; blank string = not set). */
export interface CompanyProfileValues {
  legal_name: string;
  gstin: string;
  pan: string;
  registered_address: string;
  contact_email: string;
  contact_phone: string;
}

/** The `settings.company` patch the form sends (null clears a field). */
export interface CompanyProfilePatch {
  legal_name: string | null;
  gstin: string | null;
  pan: string | null;
  registered_address: string | null;
  contact_email: string | null;
  contact_phone: string | null;
}

type RawSettings = Record<string, unknown> | null | undefined;

/**
 * Reads a nested string value, or "" when missing / not a string.
 *
 * @param source - Object to read from.
 * @param key - Key to read.
 */
function _str(source: unknown, key: string): string {
  if (!source || typeof source !== "object") return "";
  const value = (source as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

/**
 * Builds the Company Profile form values from the stored settings, preferring
 * `settings.company` and falling back to the legacy keys the backend also reads.
 *
 * @param raw - Full tenant settings from `GET /tenants/settings`.
 * @returns Form values (never undefined).
 */
export function companyValuesFromSettings(raw: RawSettings): CompanyProfileValues {
  const company = raw?.company;
  const contact = raw?.contact;
  const wallet = raw?.wallet_config;
  return {
    legal_name: _str(company, "legal_name") || _str(wallet, "merchant_name"),
    gstin:
      _str(company, "gstin") ||
      _str(wallet, "gstin") ||
      _str(contact, "gstin") ||
      _str(raw, "gstin"),
    pan: _str(company, "pan"),
    registered_address: _str(company, "registered_address") || _str(contact, "address"),
    contact_email: _str(company, "contact_email"),
    contact_phone: _str(company, "contact_phone"),
  };
}

/**
 * The stored invoice prefix, or null when none is configured.
 *
 * @param raw - Full tenant settings.
 */
export function storedInvoicePrefix(raw: RawSettings): string | null {
  return _str(raw?.company, "invoice_prefix").trim() || null;
}

/**
 * Trims a value and turns blank into null.
 *
 * @param value - Raw input.
 * @param upper - Upper-case the result (GSTIN / PAN).
 */
function _clean(value: string, upper = false): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return upper ? trimmed.toUpperCase() : trimmed;
}

/**
 * Converts form values into the `settings.company` patch.
 *
 * @param values - Company Profile form values.
 * @returns The patch (blank → null; GSTIN / PAN upper-cased).
 */
export function companyPatchFromValues(values: CompanyProfileValues): CompanyProfilePatch {
  return {
    legal_name: _clean(values.legal_name),
    gstin: _clean(values.gstin, true),
    pan: _clean(values.pan, true),
    registered_address: _clean(values.registered_address),
    contact_email: _clean(values.contact_email),
    contact_phone: _clean(values.contact_phone),
  };
}
