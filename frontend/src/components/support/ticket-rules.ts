// frontend/src/components/support/ticket-rules.ts

/** Ticket category groups (`TicketCategoryGroup` in the backend). */
export type CategoryGroupKey = "SHIPMENT_ISSUE" | "OTHER_ISSUE";

/** Sub-category a weight-claim "Need help?" link pre-selects (also a SHIPMENT ISSUE chip). */
export const CLAIMS_FINANCE_CHIP = "Claims / Finance (disputes, remittance, bank details, etc.)";

/**
 * Shipment-issue chips that are not about one AWB (remittance, bank details, ...).
 * Every other SHIPMENT ISSUE chip needs the AWB, like Delhivery One's Raise Issue form
 * (help slug `support-tickets`).
 */
const AWB_OPTIONAL_SHIPMENT_CHIPS: readonly string[] = [CLAIMS_FINANCE_CHIP];

/** True when the selected category needs an AWB before the ticket can be raised. */
export function ticketNeedsAwb(group: CategoryGroupKey, label: string): boolean {
  return group === "SHIPMENT_ISSUE" && !AWB_OPTIONAL_SHIPMENT_CHIPS.includes(label);
}

/** A "Raise a ticket" pre-fill read from the `/support?awb=...&category=...` deep link. */
export interface TicketPrefill {
  awb: string;
  category: string | null;
}

/**
 * Reads the raise-ticket deep link (used by "Need help?" on a rejected weight claim).
 *
 * @param search - `window.location.search`.
 * @returns The pre-fill, or null when the link carries no AWB.
 */
export function readTicketPrefill(search: string): TicketPrefill | null {
  const params = new URLSearchParams(search);
  const awb = (params.get("awb") || "").trim();
  if (!awb) return null;
  const category = (params.get("category") || "").trim();
  return { awb, category: category || null };
}

/** Plain-language rules behind the "Learn More" pill (Delhivery One help slug `support-tickets`). */
export const SUPPORT_HELP_POINTS: readonly string[] = [
  "Raise a ticket here: pick the issue, add the AWB for shipment issues and describe the problem.",
  "An AWB has one open ticket at a time; if one exists you are pointed to it so you can add a comment there.",
  "Open: our team is working on it. Resolved: reply in the thread to reopen it if you are not satisfied. Closed: final; raise a new ticket if you still need help.",
];
