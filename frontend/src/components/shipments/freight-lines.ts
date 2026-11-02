// frontend/src/components/shipments/freight-lines.ts
/**
 * Picks the freight breakup rows to show for a booked shipment (display only, no math).
 *
 * New bookings carry the backend's `pricing_breakdown.sell_lines` (the exact rows the quote
 * showed: freight, docket, pickup, door delivery, FOV, GST ...). Shipments booked before
 * the pricing redesign only have the legacy keys (`base_freight`, `docket_charge`,
 * `fov_charge`, `fuel_surcharge`, ...). GST is returned separately so pages can keep it on
 * its own line above the total.
 *
 * Spring analogy: a read-only view-model mapper in a `@Controller`, no business logic.
 */

/** One printable breakup row (amount straight from the API). */
export interface FreightLine {
  code: string;
  label: string;
  amount: number;
}

/** Backend `sell_lines` code of the GST row. */
export const GST_LINE_CODE = "GST";

/** Legacy optional surcharges shown only when non-zero, in this order. */
const LEGACY_OPTIONAL_LINES: ReadonlyArray<{ key: string; label: string }> = [
  { key: "oversized_surcharge", label: "Oversized Surcharge" },
  { key: "network_surcharge", label: "Network Surcharge" },
  { key: "cod_fee", label: "COD Collection Fee" },
  { key: "rto_surcharge", label: "RTO Surcharge" },
];

/** Legacy rows always shown (even at ₹0) for pre-redesign shipments. */
const LEGACY_FIXED_LINES: ReadonlyArray<{ key: string; label: string }> = [
  { key: "docket_charge", label: "Docket Fee" },
  { key: "fov_charge", label: "FOV Surcharge (Carrier's Risk)" },
  { key: "fuel_surcharge", label: "Fuel Surcharge" },
];

/** Minimal slice of `payment_details` this mapper reads. */
export interface FreightPricingSource {
  base_freight?: number | null;
  pricing_breakdown?: Record<string, unknown> | null;
}

/**
 * Coerces an API amount to a number (0 when absent or not numeric).
 *
 * @param value - Raw amount from the payload.
 * @returns The amount as a number.
 */
function amountOf(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Reads the backend `sell_lines` rows (without GST) when present.
 *
 * @param breakdown - `payment_details.pricing_breakdown`.
 * @returns The rows, or null when the shipment has no `sell_lines`.
 */
function sellLines(breakdown: Record<string, unknown>): FreightLine[] | null {
  const raw = breakdown.sell_lines;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  return raw
    .filter((line): line is Record<string, unknown> => typeof line === "object" && line !== null)
    .filter((line) => line.code !== GST_LINE_CODE)
    .map((line) => ({
      code: String(line.code ?? ""),
      label: String(line.label ?? line.code ?? ""),
      amount: amountOf(line.amount),
    }));
}

/**
 * Legacy rows for shipments priced before `sell_lines` existed.
 *
 * @param pricing - `payment_details`.
 * @param breakdown - `payment_details.pricing_breakdown` (may be empty).
 * @returns Base freight, the fixed legacy rows, then non-zero optional surcharges.
 */
function legacyLines(pricing: FreightPricingSource, breakdown: Record<string, unknown>): FreightLine[] {
  const fixed = LEGACY_FIXED_LINES.map(({ key, label }) => ({
    code: key,
    label,
    amount: amountOf(breakdown[key]),
  }));
  const optional = LEGACY_OPTIONAL_LINES.map(({ key, label }) => ({
    code: key,
    label,
    amount: amountOf(breakdown[key]),
  })).filter((line) => line.amount > 0);
  return [
    { code: "base_freight", label: "Base Freight", amount: amountOf(pricing.base_freight) },
    ...fixed,
    ...optional,
  ];
}

/**
 * Freight breakup rows (pre-GST) for a booked shipment.
 *
 * @param pricing - The shipment's `payment_details` (or null while loading).
 * @returns Rows to print above the GST and total lines.
 */
export function freightBreakupLines(pricing: FreightPricingSource | null | undefined): FreightLine[] {
  if (!pricing) return [];
  const breakdown = (pricing.pricing_breakdown ?? {}) as Record<string, unknown>;
  return sellLines(breakdown) ?? legacyLines(pricing, breakdown);
}
