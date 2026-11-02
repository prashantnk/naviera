// frontend/src/app/[tenant_slug]/(app)/b2b/appointments/_components/appointment-helpers.ts
/**
 * Pure helpers for the B2B Manage Appointments page (unit tested, no React).
 */
import { AppointmentTab, PickupStatus, PickupTimeSlot } from "@/api_client";
import { safeFormatDate, toIstIsoString } from "@/lib/utils";
import { MAX_PO_NUMBERS, splitPoNumbers } from "@/lib/validations/shipment";

/** Tabs in Delhivery order with their labels. */
export const APPOINTMENT_TABS: readonly { tab: AppointmentTab; label: string }[] = [
  { tab: AppointmentTab.PENDING, label: "Pending" },
  { tab: AppointmentTab.AT_RISK, label: "At risk" },
  { tab: AppointmentTab.BOOKED, label: "Booked" },
];

/** Shipment statuses in which an appointment can still be booked (backend rule). */
export const APPOINTMENT_STATUS_FILTERS: readonly PickupStatus[] = [
  PickupStatus.OPEN,
  PickupStatus.ASSIGNED,
  PickupStatus.IN_TRANSIT,
  PickupStatus.EXCEPTION,
];

/** Rows-per-page choices (Delhivery default 20). */
export const APPOINTMENT_PAGE_SIZES: readonly number[] = [20, 50, 100];
export const DEFAULT_APPOINTMENT_PAGE_SIZE = 20;

/** Date format for "PO expiry" and "Delivery by". */
const DISPLAY_DATE_FORMAT = "dd MMM yyyy";
const SHORT_DATE_FORMAT = "dd MMM";

/** PO column state. */
export enum PoState {
  MISSING = "MISSING",
  EXPIRED = "EXPIRED",
  VALID = "VALID",
}

/**
 * Decides what the PO expiry column shows.
 *
 * @param row - Flags and expiry date from the API.
 * @returns MISSING / EXPIRED (red in the UI) or VALID.
 */
export function resolvePoState(row: {
  po_missing: boolean;
  po_expired: boolean;
  po_expiry_date?: string | null;
}): PoState {
  if (row.po_missing) return PoState.MISSING;
  if (row.po_expired) return PoState.EXPIRED;
  return PoState.VALID;
}

/**
 * Formats an API date (`yyyy-MM-dd` or ISO timestamp) for display.
 *
 * @param value - API value.
 * @param short - Omit the year ("22 Oct").
 * @returns Formatted date, or null when missing/invalid.
 */
export function formatAppointmentDate(value: string | null | undefined, short = false): string | null {
  if (!value) return null;
  const formatted = safeFormatDate(value, short ? SHORT_DATE_FORMAT : DISPLAY_DATE_FORMAT);
  return formatted === "-" ? null : formatted;
}

/**
 * Converts a date + slot ("10:00 - 14:00") into the ISO window the API expects.
 * Interprets the date and slot in `Asia/Kolkata` (IST, +05:30) (D-09).
 *
 * @param date - IST date `yyyy-MM-dd`.
 * @param slot - Time slot enum value.
 * @returns ISO start and end timestamps.
 */
export function slotToIsoWindow(
  date: string,
  slot: PickupTimeSlot
): { appointment_start: string; appointment_end: string } {
  const [startClock, endClock] = slot.split(" - ");
  return {
    appointment_start:
      toIstIsoString(`${date}T${startClock}:00`) ??
      new Date(`${date}T${startClock}:00+05:30`).toISOString(),
    appointment_end:
      toIstIsoString(`${date}T${endClock}:00`) ??
      new Date(`${date}T${endClock}:00+05:30`).toISOString(),
  };
}

/**
 * Finds the slot whose start matches an existing appointment (to prefill reschedules).
 *
 * @param startIso - Existing appointment start (ISO).
 * @returns IST date and matching slot, or nulls when unknown.
 */
export function isoToDateAndSlot(startIso: string | null | undefined): {
  date: string | null;
  slot: PickupTimeSlot | null;
} {
  if (!startIso) return { date: null, slot: null };
  const datePart = safeFormatDate(startIso, "yyyy-MM-dd");
  const startClock = safeFormatDate(startIso, "HH:mm");
  if (datePart === "-" || startClock === "-") return { date: null, slot: null };
  const slot =
    Object.values(PickupTimeSlot).find((value) => value.startsWith(startClock)) ?? null;
  return { date: datePart, slot };
}

/**
 * Validation for the single "Book appointment" form (all four fields required).
 *
 * @param values - Form values.
 * @returns Field → error message (empty when valid).
 */
export function validateBookAppointment(values: {
  poNumber: string;
  poExpiry: string;
  date: string;
  slot: string;
}): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.poNumber.trim()) {
    errors.poNumber = "PO number is required";
  } else if (splitPoNumbers(values.poNumber).length > MAX_PO_NUMBERS) {
    errors.poNumber = `Maximum ${MAX_PO_NUMBERS} comma-separated PO numbers are allowed`;
  }
  if (!values.poExpiry) {
    errors.poExpiry = "PO expiry date is required";
  } else if (values.date && values.poExpiry < values.date) {
    errors.poExpiry = "PO expiry date cannot be earlier than the appointment date";
  }
  if (!values.date) errors.date = "Appointment date is required";
  if (!values.slot) errors.slot = "Appointment time is required";
  return errors;
}
