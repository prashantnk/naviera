// frontend/src/components/pickups/pickup-constants.ts
/**
 * Flow-aware constants for Pickup Requests (Delhivery "PUR") in B2C and B2B.
 *
 * Every route, label and copy string used by the shared Pickup Requests
 * components lives here so the B2C and B2B pages differ only by the
 * `ServiceFlow` they pass in.
 *
 * Spring Boot analogy: an `@ConfigurationProperties` bean keyed by flow.
 */
import { PickupTimeSlot, ServiceFlow } from "@/api_client";
import { PICKUP_TIME_SLOT_OPTIONS } from "@/lib/form-options";
import { addDays, format, isSunday, parseISO } from "date-fns";

/** Static copy and routes for one business flow. */
export interface PickupFlowConfig {
  /** Tenant-relative list route. */
  listHref: string;
  /** Tenant-relative create route. */
  createHref: string;
  /** Short shipment identifier noun: "AWB" for parcels, "LRN" for cargo. */
  shipmentNoun: string;
  /** Column header for the shipment identifier in the create picker. */
  shipmentIdHeader: string;
  /** Whether the flow supports blind pickups and a declared box count. */
  allowBlindPickup: boolean;
  /** Same-day cut-off hint shown on the create form, or null when none applies. */
  sameDayCutoffNote: string | null;
  /** Hint shown under the shipment picker. */
  pickerHint: string;
}

/** Same-day pickup cut-off in IST (matches backend `DEFAULT_CUTOFF = "13:00"`, D-10). */
export const SAME_DAY_CUTOFF_LABEL = "1 PM";
const B2B_SAME_DAY_CUTOFF_LABEL = SAME_DAY_CUTOFF_LABEL;

export const PICKUP_FLOW_CONFIG: Readonly<Record<ServiceFlow, PickupFlowConfig>> = {
  [ServiceFlow.B2C]: {
    listHref: "/pickup-requests",
    createHref: "/pickup-requests/new",
    shipmentNoun: "AWB",
    shipmentIdHeader: "AWB",
    allowBlindPickup: false,
    sameDayCutoffNote: `Create the pickup request before ${SAME_DAY_CUTOFF_LABEL} for same-day pickup.`,
    pickerHint:
      "Only Ready to Ship shipments manifested from this pickup location are listed. Print and paste labels before the pickup.",
  },
  [ServiceFlow.B2B]: {
    listHref: "/b2b/pickup-requests",
    createHref: "/b2b/pickup-requests/new",
    shipmentNoun: "LRN",
    shipmentIdHeader: "LRN / AWB",
    allowBlindPickup: true,
    sameDayCutoffNote: `Create the pickup request before ${B2B_SAME_DAY_CUTOFF_LABEL} for same-day pickup.`,
    pickerHint:
      "Only Ready to Ship LRs booked from this pickup location are listed. Paste the LR dockets and box labels before the pickup.",
  },
};

/** Shared page header copy (identical in both flows, Delhivery wording). */
export const PICKUP_PAGE_TITLE = "Pickup Requests";
export const PICKUP_PAGE_SUBTITLE = "Create and manage all your pickups here.";
export const CREATE_PICKUP_TITLE = "Create Pickup Request";

/** Delhivery pickup slots in display order. Values are the stored enum strings. */
export const PICKUP_SLOT_ORDER: readonly PickupTimeSlot[] = [
  PickupTimeSlot._06_00_10_00,
  PickupTimeSlot._10_00_14_00,
  PickupTimeSlot._14_00_18_00,
  PickupTimeSlot._18_00_22_00,
];

/** 24h start hour of each slot, used to grey out slots that already started today. */
export const PICKUP_SLOT_START_HOUR: Readonly<Record<PickupTimeSlot, number>> = {
  [PickupTimeSlot._06_00_10_00]: 6,
  [PickupTimeSlot._10_00_14_00]: 10,
  [PickupTimeSlot._14_00_18_00]: 14,
  [PickupTimeSlot._18_00_22_00]: 18,
};

/** Default slot when nothing else applies (Delhivery's most common afternoon slot). */
export const DEFAULT_PICKUP_SLOT: PickupTimeSlot = PickupTimeSlot._14_00_18_00;

/** Delhivery-style slot labels use a plain hyphen, e.g. "02:00 PM - 06:00 PM". */
const SLOT_LABEL_SEPARATOR = " - ";
const SLOT_LABEL_DASH_PATTERN = /\s*\u2013\s*/;

/** API date format (`yyyy-MM-dd`) used for `scheduled_date`. */
export const API_DATE_FORMAT = "yyyy-MM-dd";
/** Delhivery list date format, e.g. "15 Oct, 2026". */
export const PICKUP_DISPLAY_DATE_FORMAT = "dd MMM, yyyy";

/** Query parameter names used to prefill the create page. */
export const PICKUP_QUERY_PARAMS = {
  location: "location",
  locationName: "location_name",
  shipments: "shipments",
  date: "date",
} as const;

/** Separator for the comma-joined `shipments` query parameter. */
export const SHIPMENT_IDS_SEPARATOR = ",";

/** Preset reasons for the Admin "Not picked" outcome (Delhivery wording). */
export const NOT_PICKED_REASONS: readonly string[] = [
  "Shipment not ready for pickup",
  "Pickup not attempted - Not Dispatched",
  "Seller / warehouse closed",
  "Pickup location not reachable",
  "Packaging not proper",
  "Pickup executive could not reach in slot",
];

/** Sentinel select value for a free-text Not picked reason. */
export const OTHER_REASON_VALUE = "__other__";

/** Supported merged label PDF formats for "Print label". */
export enum PickupLabelFormat {
  A4 = "a4",
  THERMAL_4X2 = "thermal_4x2",
}

/**
 * Returns the Delhivery-style label for a stored time slot value.
 *
 * @param slot - Stored slot string, e.g. "14:00 - 18:00".
 * @returns e.g. "02:00 PM - 06:00 PM", or the raw value for unknown slots.
 */
export function getPickupSlotLabel(slot: string): string {
  const meta = PICKUP_TIME_SLOT_OPTIONS[slot as PickupTimeSlot];
  return meta ? meta.label.split(SLOT_LABEL_DASH_PATTERN).join(SLOT_LABEL_SEPARATOR) : slot;
}

/**
 * Formats an API `yyyy-MM-dd` date as a local calendar date (no UTC shift).
 *
 * @param isoDate - Date string from the API.
 * @returns e.g. "15 Oct, 2026", or "-" when missing / invalid.
 */
export function formatPickupDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "-";
  const parsed = parseISO(isoDate);
  return Number.isNaN(parsed.getTime()) ? "-" : format(parsed, PICKUP_DISPLAY_DATE_FORMAT);
}

/**
 * Today's local date in API format.
 *
 * @returns e.g. "2026-10-16".
 */
export function todayApiDate(): string {
  return format(new Date(), API_DATE_FORMAT);
}

/**
 * Next working day (skips Sundays) in API format, used by "Reschedule".
 *
 * @param from - Reference date (defaults to now).
 * @returns API date string of the next non-Sunday day.
 */
export function nextWorkingApiDate(from: Date = new Date()): string {
  let next = addDays(from, 1);
  while (isSunday(next)) {
    next = addDays(next, 1);
  }
  return format(next, API_DATE_FORMAT);
}

/**
 * Whether a slot has already started on the selected date (only true for today).
 *
 * @param slot - Slot enum value.
 * @param scheduledDate - Selected API date.
 * @param now - Current time (injectable for tests).
 * @returns True when the slot can no longer be booked for that date.
 */
export function isPickupSlotPassed(
  slot: PickupTimeSlot,
  scheduledDate: string,
  now: Date = new Date()
): boolean {
  if (scheduledDate !== format(now, API_DATE_FORMAT)) return false;
  return now.getHours() >= PICKUP_SLOT_START_HOUR[slot];
}

/**
 * Picks the first bookable slot for a date, falling back to the default slot.
 *
 * @param scheduledDate - Selected API date.
 * @param now - Current time (injectable for tests).
 * @returns A slot that has not started yet, or `DEFAULT_PICKUP_SLOT`.
 */
export function firstAvailablePickupSlot(
  scheduledDate: string,
  now: Date = new Date()
): PickupTimeSlot {
  const open = PICKUP_SLOT_ORDER.find((slot) => !isPickupSlotPassed(slot, scheduledDate, now));
  return open ?? DEFAULT_PICKUP_SLOT;
}

/**
 * Builds the create-page URL (tenant-relative) with prefill query params.
 *
 * @param flow - Target business flow.
 * @param prefill - Optional location, location name, shipment ids and date.
 * @returns e.g. "/pickup-requests/new?location=...&shipments=a,b".
 */
export function buildCreatePickupHref(
  flow: ServiceFlow,
  prefill: {
    locationId?: string;
    locationName?: string;
    shipmentIds?: readonly string[];
    date?: string;
  }
): string {
  const params = new URLSearchParams();
  if (prefill.locationId) params.set(PICKUP_QUERY_PARAMS.location, prefill.locationId);
  if (prefill.locationName) params.set(PICKUP_QUERY_PARAMS.locationName, prefill.locationName);
  if (prefill.shipmentIds && prefill.shipmentIds.length > 0) {
    params.set(PICKUP_QUERY_PARAMS.shipments, prefill.shipmentIds.join(SHIPMENT_IDS_SEPARATOR));
  }
  if (prefill.date) params.set(PICKUP_QUERY_PARAMS.date, prefill.date);
  const query = params.toString();
  const base = PICKUP_FLOW_CONFIG[flow].createHref;
  return query ? `${base}?${query}` : base;
}

/**
 * Human-readable Pickup ID: the 9-digit number, or a short UUID for legacy rows.
 *
 * @param manifest - Object with `id` and optional `pickup_request_number`.
 * @returns Display identifier.
 */
export function getPickupDisplayId(manifest: {
  id: string;
  pickup_request_number?: string | null;
}): string {
  return manifest.pickup_request_number || manifest.id.slice(0, 8).toUpperCase();
}
