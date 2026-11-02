// frontend/src/components/shipments/shipment-display.ts
/**
 * Small display helpers for the B2C shipment detail page (journey audit 2026-11-01).
 *
 * Pure functions only: they pick labels for values the backend already sent, so the
 * page reads like Delhivery One ("Delhivery Surface", "Not scheduled yet") instead of
 * raw enum values ("SURFACE_ROAD") or a pickup date that was never chosen.
 *
 * Spring analogy: a tiny stateless view-helper (`@Component` formatter).
 */
import type { PickupRead } from "@/api_client";
import { SERVICE_OPTION_OPTIONS, getOptionMeta } from "@/lib/form-options";
import { safeFormatDate } from "@/lib/utils";

/** Shown in "Pickup date" until the order is added to a pickup request (Delhivery PUR). */
export const PICKUP_NOT_SCHEDULED_LABEL = "Not scheduled yet";

/** Stage timestamps on the tracking stepper, in IST ("01 Nov 2026 · 2:29 PM"). */
export const STAGE_TIMESTAMP_FORMAT = "dd MMM yyyy · h:mm a";

/** Calendar format of the scheduled pickup date ("01 Nov 2026"). */
const PICKUP_DATE_FORMAT = "dd MMM yyyy";

/**
 * Human label of the booked service (e.g. "Delhivery Express").
 *
 * @param shipment - Shipment with `service_option` (new bookings) and legacy `service_type`.
 * @returns The option label, or the legacy service type in words for old rows.
 */
export function serviceLabel(shipment: Pick<PickupRead, "service_option" | "service_type">): string {
  const meta = getOptionMeta(SERVICE_OPTION_OPTIONS, shipment.service_option);
  if (meta) return meta.label;
  return String(shipment.service_type ?? "")
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * The pickup date to show: the pickup request's scheduled date once the order is on
 * one, otherwise "Not scheduled yet" (booking only "manifests" the order).
 *
 * @param scheduledDate - `scheduled_date` of the linked pickup request, if any.
 * @param isOnPickupRequest - Whether the shipment is linked to a pickup request.
 * @returns Display text.
 */
export function pickupDateLabel(scheduledDate: string | null | undefined, isOnPickupRequest: boolean): string {
  if (!isOnPickupRequest || !scheduledDate) return PICKUP_NOT_SCHEDULED_LABEL;
  return safeFormatDate(scheduledDate, PICKUP_DATE_FORMAT);
}

/**
 * Formats a backend timestamp for the tracking stepper in IST (naive values are UTC).
 *
 * @param value - API timestamp.
 * @returns Display text, or undefined when missing/unparseable.
 */
export function stageTimestampLabel(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const text = safeFormatDate(value, STAGE_TIMESTAMP_FORMAT);
  return text === "-" ? undefined : text;
}
