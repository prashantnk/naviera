// frontend/src/components/booking/use-shipment-valuation.ts
"use client";

/**
 * D-06: keeps the read-only "Total Value" and the e-way bill rule in sync with the
 * backend (`POST /api/v1/shipments/valuation`) while the user types goods value/tax.
 * The browser never adds value + tax itself (Zero Frontend Math).
 */
import { useEffect, useState } from "react";
import { fetchShipmentValuation, type ShipmentValuation } from "./booking-api";

/** Wait this long after the last keystroke before asking the backend. */
export const VALUATION_DEBOUNCE_MS = 400;

/**
 * Normalises a form number (may be "" or NaN while typing) to a non-negative amount.
 *
 * @param value - Raw form value.
 * @returns The amount to send, or 0.
 */
export function toValuationInput(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

/**
 * Debounced backend valuation for the given goods value and tax.
 *
 * @param shipmentValue - Goods value field (raw form value).
 * @param shipmentTaxValue - Goods tax field (raw form value).
 * @param onValuation - Called with every fresh valuation (e.g. to mirror it into the form).
 * @returns The latest valuation (null until the first answer).
 */
export function useShipmentValuation(
  shipmentValue: unknown,
  shipmentTaxValue: unknown,
  onValuation?: (valuation: ShipmentValuation) => void,
): { valuation: ShipmentValuation | null } {
  const [valuation, setValuation] = useState<ShipmentValuation | null>(null);
  const value = toValuationInput(shipmentValue);
  const tax = toValuationInput(shipmentTaxValue);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const result = await fetchShipmentValuation(value, tax);
        if (cancelled) return;
        setValuation(result);
        onValuation?.(result);
      } catch {
        // Keep the last good valuation; the booking re-validates on the server anyway.
      }
    }, VALUATION_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `onValuation` is a callback prop; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, tax]);

  return { valuation };
}
