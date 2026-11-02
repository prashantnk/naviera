// frontend/src/components/shipments/shipment-money.ts
/**
 * Display-only formatters for backend money and weight values (Zero Frontend Math).
 *
 * Every number passed in here already comes from an API payload. These helpers only
 * turn it into text; they never add, subtract or round business values. Signed deltas
 * use `Intl.NumberFormat`'s `signDisplay` so we never negate a number ourselves.
 *
 * Spring analogy: a Thymeleaf `#numbers.formatCurrency(...)` utility, nothing more.
 */

/** Placeholder rendered when the backend sent no value. */
export const EMPTY_VALUE = "—";

const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const KG_FORMATTER = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Converts an API money value (JSON number, or a Decimal serialised as a string) to a number.
 *
 * @param value - Raw value from the payload.
 * @returns The parsed number, or null when the value is absent or not numeric.
 */
export function toDisplayNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Formats a backend rupee amount, e.g. `₹1,234.50`.
 *
 * @param value - Amount from the API.
 * @returns Formatted rupees, or an em dash when absent.
 */
export function formatInr(value: number | string | null | undefined): string {
  const amount = toDisplayNumber(value);
  return amount === null ? EMPTY_VALUE : INR_FORMATTER.format(amount);
}

/**
 * Formats a backend signed delta, e.g. `₹389.40`, `-₹120.00` or `₹0.00`.
 * Uses standard INR formatting (without a leading `+`) so UI money parsers (`parse_rupees`)
 * can parse the exact rupee text directly.
 *
 * @param value - Signed delta from the API (new total minus old total, computed server-side).
 * @returns Formatted signed rupees, or an em dash when absent.
 */
export function formatSignedInr(value: number | string | null | undefined): string {
  const amount = toDisplayNumber(value);
  return amount === null ? EMPTY_VALUE : INR_FORMATTER.format(amount);
}

/**
 * Formats a backend weight in kilograms, e.g. `24.00 kg`.
 *
 * @param value - Weight from the API.
 * @returns Formatted weight, or an em dash when absent.
 */
export function formatKg(value: number | string | null | undefined): string {
  const weight = toDisplayNumber(value);
  return weight === null ? EMPTY_VALUE : `${KG_FORMATTER.format(weight)} kg`;
}

/** Visual direction of a backend delta, used only to pick a colour token. */
export type DeltaDirection = "up" | "down" | "none";

/**
 * Classifies a backend delta for colouring (comparison only, no arithmetic).
 *
 * @param value - Signed delta from the API.
 * @returns `up` for a charge, `down` for a refund, `none` for zero or absent.
 */
export function deltaDirection(value: number | string | null | undefined): DeltaDirection {
  const amount = toDisplayNumber(value);
  if (amount === null || amount === 0) return "none";
  return amount > 0 ? "up" : "down";
}
