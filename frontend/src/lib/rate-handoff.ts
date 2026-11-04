// frontend/src/lib/rate-handoff.ts
/**
 * Rate calculator -> booking wizard hand-off.
 *
 * When a merchant clicks "Book This Shipment" on the rate calculator, the
 * quote inputs travel in the query string so the forward wizard opens
 * pre-filled (Delhivery parity: "Ship now" from the rate card). Only raw
 * user inputs are passed (pincodes, box dimensions, category, COD). No prices
 * are passed; the wizard re-quotes on the server.
 */

/** Query keys used by the hand-off (short so links stay readable). */
export const RATE_HANDOFF_KEYS = {
  origin: "origin",
  destination: "dest",
  length: "l",
  breadth: "b",
  height: "h",
  weight: "weight",
  boxes: "boxes",
  description: "desc",
  category: "category",
  isCod: "cod",
  codAmount: "cod_amount",
  shipmentValue: "value",
  doorDelivery: "door",
} as const;

/** Fields the rate calculator can hand to a booking wizard. */
export interface RateHandoff {
  originPincode?: string;
  destinationPincode?: string;
  length?: number;
  breadth?: number;
  height?: number;
  weightKg?: number;
  boxCount?: number;
  description?: string;
  productCategory?: string;
  isCod?: boolean;
  codAmount?: number;
  shipmentValue?: number;
  doorDelivery?: boolean;
}

const PINCODE_PATTERN = /^[1-9][0-9]{5}$/;

/**
 * Parses a positive finite number, ignoring blanks, zero and garbage.
 *
 * @param raw - Raw query-string value.
 * @returns The number, or undefined when missing or invalid.
 */
function positiveNumber(raw: string | null): number | undefined {
  if (raw === null || raw.trim() === "") return undefined;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

/**
 * Parses a 6-digit Indian pincode.
 *
 * @param raw - Raw query-string value.
 * @returns The pincode, or undefined when invalid.
 */
function pincode(raw: string | null): string | undefined {
  const value = (raw || "").trim();
  return PINCODE_PATTERN.test(value) ? value : undefined;
}

/**
 * Builds the hand-off query string (without the leading `?`).
 *
 * @param handoff - Values entered on the rate calculator.
 * @returns URL-encoded query string; empty when nothing is worth passing.
 */
export function buildRateHandoffQuery(handoff: RateHandoff): string {
  const params = new URLSearchParams();
  const put = (key: string, value: string | number | boolean | undefined) => {
    if (value === undefined || value === "" || value === false) return;
    // Zero / negative numbers are form defaults ("not entered"), not real inputs.
    if (typeof value === "number" && !(Number.isFinite(value) && value > 0)) return;
    params.set(key, String(value));
  };
  put(RATE_HANDOFF_KEYS.origin, handoff.originPincode);
  put(RATE_HANDOFF_KEYS.destination, handoff.destinationPincode);
  put(RATE_HANDOFF_KEYS.length, handoff.length);
  put(RATE_HANDOFF_KEYS.breadth, handoff.breadth);
  put(RATE_HANDOFF_KEYS.height, handoff.height);
  put(RATE_HANDOFF_KEYS.weight, handoff.weightKg);
  put(RATE_HANDOFF_KEYS.boxes, handoff.boxCount);
  const cleanDescription = (handoff.description || "").trim();
  if (cleanDescription) {
    put(RATE_HANDOFF_KEYS.description, cleanDescription);
  }
  put(RATE_HANDOFF_KEYS.category, handoff.productCategory);
  if (handoff.isCod) {
    put(RATE_HANDOFF_KEYS.isCod, "1");
    put(RATE_HANDOFF_KEYS.codAmount, handoff.codAmount);
  }
  put(RATE_HANDOFF_KEYS.shipmentValue, handoff.shipmentValue);
  if (handoff.doorDelivery) {
    put(RATE_HANDOFF_KEYS.doorDelivery, "1");
  }
  return params.toString();
}

/**
 * Parses the hand-off from a query string.
 *
 * @param search - `window.location.search` (with or without `?`).
 * @param allowedCategories - Valid `ProductCategory` values; others are dropped.
 * @returns Parsed hand-off, or null when the URL carries no usable hand-off data.
 */
export function parseRateHandoff(
  search: string,
  allowedCategories: readonly string[],
): RateHandoff | null {
  const params = new URLSearchParams(search);
  const category = params.get(RATE_HANDOFF_KEYS.category) || "";
  const description = (params.get(RATE_HANDOFF_KEYS.description) || "").trim();
  const isCod = params.get(RATE_HANDOFF_KEYS.isCod) === "1";
  const doorDelivery = params.get(RATE_HANDOFF_KEYS.doorDelivery) === "1";
  const handoff: RateHandoff = {
    originPincode: pincode(params.get(RATE_HANDOFF_KEYS.origin)),
    destinationPincode: pincode(params.get(RATE_HANDOFF_KEYS.destination)),
    length: positiveNumber(params.get(RATE_HANDOFF_KEYS.length)),
    breadth: positiveNumber(params.get(RATE_HANDOFF_KEYS.breadth)),
    height: positiveNumber(params.get(RATE_HANDOFF_KEYS.height)),
    weightKg: positiveNumber(params.get(RATE_HANDOFF_KEYS.weight)),
    boxCount: positiveNumber(params.get(RATE_HANDOFF_KEYS.boxes)),
    description: description || undefined,
    productCategory: allowedCategories.includes(category) ? category : undefined,
    isCod: isCod || undefined,
    codAmount: isCod ? positiveNumber(params.get(RATE_HANDOFF_KEYS.codAmount)) : undefined,
    shipmentValue: positiveNumber(params.get(RATE_HANDOFF_KEYS.shipmentValue)),
    doorDelivery: doorDelivery ? true : undefined,
  };
  const hasData = Object.values(handoff).some((value) => value !== undefined);
  return hasData ? handoff : null;
}

/** Minimal address shape needed to match a pincode against the address book. */
export interface PincodeAddress {
  id: string;
  pincode: string;
}

/**
 * Picks the first saved address with the given pincode.
 *
 * @param addresses - Saved address book entries.
 * @param targetPincode - Pincode from the hand-off.
 * @param excludeId - Address already used for the other leg (avoid same pickup and drop).
 * @returns Matching address id, or undefined.
 */
export function matchAddressByPincode(
  addresses: readonly PincodeAddress[],
  targetPincode: string | undefined,
  excludeId?: string,
): string | undefined {
  if (!targetPincode) return undefined;
  return addresses.find((a) => a.pincode === targetPincode && a.id !== excludeId)?.id;
}
