// frontend/src/app/[tenant_slug]/(app)/ops/ops-field.ts
/**
 * Pure, display-only rules for the Operations / Field Executive app (WP9).
 *
 * Every "can the rider do X now?" question is answered from the server's
 * `PickupRead.allowed_next_statuses` (computed by `ShipmentLifecycleMachine`), and every
 * rupee shown comes from `PickupRead.door_collectible` (`services/cod_payout.py`). Nothing
 * here computes money or re-implements the state machine (Zero Frontend Math).
 *
 * Spring Boot analogy: a stateless view-helper `@Component` that maps DTO fields to UI flags.
 */
import {
  CodRemittanceStatus,
  ManifestStatus,
  NdrExceptionReason,
  PickupRead,
  PickupStatus,
  ShipmentType,
} from "@/api_client";
import {
  NDR_REASON_OPTIONS,
  SERVICE_TYPE_OPTIONS,
  getOptionMeta,
  toOptions,
} from "@/lib/form-options";

/** Delivery-tab filter keys that are not a single `PickupStatus`. */
export enum DeliveryFilterKey {
  ACTIVE = "ACTIVE",
  RTO = "RTO",
  ALL = "ALL",
}

export type DeliveryFilter = DeliveryFilterKey | PickupStatus;

/** Statuses shown on the Last-Mile tab at all (D-01: OFD and RTO legs included). */
export const DELIVERY_VIEW_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.OPEN,
  PickupStatus.ASSIGNED,
  PickupStatus.IN_TRANSIT,
  PickupStatus.OUT_FOR_DELIVERY,
  PickupStatus.EXCEPTION,
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
  PickupStatus.COMPLETED,
  PickupStatus.QC_FAILED,
]);

/** Parcels on today's run-sheet: in the network, out for delivery or on the way back. */
const ACTIVE_RUNSHEET_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.IN_TRANSIT,
  PickupStatus.OUT_FOR_DELIVERY,
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
]);

/** Pre-pickup statuses in which a reverse (customer return) pickup is still field work. */
const REVERSE_PICKUP_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.OPEN,
  PickupStatus.ASSIGNED,
]);

/** RTO legs that still need a field move. */
export const RTO_LEG_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
]);

/**
 * Doorstep NDR reasons a rider can log (E-07), Delhivery One wording from `NDR_REASON_OPTIONS`.
 * Charge-bearing reasons (freight collection, additional charges, weight discrepancy) are
 * raised by staff from the order page, never typed by a rider at the door.
 */
export const FIELD_NDR_REASONS: readonly NdrExceptionReason[] = [
  NdrExceptionReason.CONSIGNEE_UNAVAILABLE,
  NdrExceptionReason.CONSIGNEE_REFUSED,
  NdrExceptionReason.DELIVERY_RESCHEDULED,
  NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED,
  NdrExceptionReason.PAYMENT_DISPUTE,
  NdrExceptionReason.DAMAGED,
  NdrExceptionReason.EWAY_BILL_MISSING,
  NdrExceptionReason.DOCUMENT_NEEDED,
  NdrExceptionReason.APPOINTMENT_NEEDED,
];

export const FIELD_NDR_SELECT_OPTIONS = toOptions(NDR_REASON_OPTIONS, FIELD_NDR_REASONS);

/**
 * Whether the server would accept moving `shipment` to `next` right now.
 *
 * @param shipment - Shipment row from the API.
 * @param next - Target status.
 * @returns True when `next` is in `allowed_next_statuses`.
 */
export function canMoveTo(shipment: Pick<PickupRead, "allowed_next_statuses">, next: PickupStatus): boolean {
  return (shipment.allowed_next_statuses ?? []).includes(next);
}

/**
 * Whether a shipment belongs on the active run-sheet (default Last-Mile filter).
 *
 * @param shipment - Shipment row from the API.
 * @returns True for in-network, OFD and RTO parcels, plus reverse pickups not yet collected.
 */
export function isActiveRunsheet(shipment: Pick<PickupRead, "status" | "shipment_type">): boolean {
  if (ACTIVE_RUNSHEET_STATUSES.has(shipment.status)) return true;
  return shipment.shipment_type === ShipmentType.REVERSE && REVERSE_PICKUP_STATUSES.has(shipment.status);
}

/**
 * Whether a shipment matches the selected Last-Mile filter chip.
 *
 * @param shipment - Shipment row from the API.
 * @param filter - Selected filter key.
 * @returns True when the row should be listed.
 */
export function matchesDeliveryFilter(
  shipment: Pick<PickupRead, "status" | "shipment_type">,
  filter: DeliveryFilter,
): boolean {
  if (!DELIVERY_VIEW_STATUSES.has(shipment.status)) return false;
  switch (filter) {
    case DeliveryFilterKey.ALL:
      return true;
    case DeliveryFilterKey.ACTIVE:
      return isActiveRunsheet(shipment);
    case DeliveryFilterKey.RTO:
      return RTO_LEG_STATUSES.has(shipment.status);
    default:
      return shipment.status === filter;
  }
}

/** Display tone of a cash-tab badge (mapped to semantic classes by the page). */
export enum CashBadgeTone {
  PENDING = "PENDING",
  WITH_FIELD_TEAM = "WITH_FIELD_TEAM",
  SETTLED = "SETTLED",
  NOT_COLLECTED = "NOT_COLLECTED",
}

export interface CashBadge {
  label: string;
  tone: CashBadgeTone;
}

/**
 * Honest door-cash state for the Field Cash tab (E-09): a delivered COD parcel is
 * "cash with field team" until the cash is actually handed in or remitted.
 *
 * @param shipment - Shipment row from the API.
 * @returns Badge label + tone.
 */
export function cashCollectionBadge(
  shipment: Pick<PickupRead, "status" | "payment_details">,
): CashBadge {
  const remit = shipment.payment_details?.cod_remittance_status;
  if (remit === CodRemittanceStatus.REMITTED) return { label: "Remitted to seller", tone: CashBadgeTone.SETTLED };
  if (remit === CodRemittanceStatus.COLLECTED) return { label: "Cash handed in", tone: CashBadgeTone.SETTLED };
  if (remit === CodRemittanceStatus.FAILED_RTO) return { label: "Not collected (RTO)", tone: CashBadgeTone.NOT_COLLECTED };
  if (shipment.status === PickupStatus.COMPLETED) {
    return { label: "Delivered · cash with field team", tone: CashBadgeTone.WITH_FIELD_TEAM };
  }
  return { label: "To collect at door", tone: CashBadgeTone.PENDING };
}

/** Field-cash statuses whose door cash is still to be collected. */
const DOOR_CASH_PENDING_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.IN_TRANSIT,
  PickupStatus.OUT_FOR_DELIVERY,
  PickupStatus.EXCEPTION,
]);

/**
 * Whether the rider still has to collect cash for this parcel (KPI "Doorstep Cash Queue").
 *
 * @param shipment - Shipment row from the API.
 * @returns True when the backend door amount is positive and the parcel is still out there.
 */
export function isDoorCashPending(shipment: Pick<PickupRead, "status" | "door_collectible">): boolean {
  return shipment.door_collectible > 0 && DOOR_CASH_PENDING_STATUSES.has(shipment.status);
}

// --- E-10: keep typed doorstep inputs across a reload / lost signal -------------------------

/** Doorstep inputs a rider typed, keyed by shipment id. */
export interface PodDraft {
  otp: Record<string, string>;
  receiver: Record<string, string>;
}

export const EMPTY_POD_DRAFT: PodDraft = { otp: {}, receiver: {} };

/**
 * sessionStorage key for one tenant's doorstep drafts (per tab, cleared when the tab closes).
 *
 * @param tenantSlug - Current tenant slug.
 * @returns The storage key.
 */
export function podDraftStorageKey(tenantSlug: string): string {
  return `ops.pod-draft.${tenantSlug}`;
}

/**
 * Reads the saved doorstep drafts; a missing or corrupt entry yields an empty draft.
 *
 * @param storage - `window.sessionStorage` (injectable for tests).
 * @param tenantSlug - Current tenant slug.
 * @returns The saved draft.
 */
export function loadPodDraft(storage: Storage, tenantSlug: string): PodDraft {
  try {
    const parsed = JSON.parse(storage.getItem(podDraftStorageKey(tenantSlug)) ?? "null") as Partial<PodDraft> | null;
    return { otp: parsed?.otp ?? {}, receiver: parsed?.receiver ?? {} };
  } catch {
    return EMPTY_POD_DRAFT;
  }
}

/**
 * Saves the doorstep drafts (best effort: private mode / quota errors are ignored).
 *
 * @param storage - `window.sessionStorage`.
 * @param tenantSlug - Current tenant slug.
 * @param draft - Inputs to keep.
 */
export function savePodDraft(storage: Storage, tenantSlug: string, draft: PodDraft): void {
  try {
    storage.setItem(podDraftStorageKey(tenantSlug), JSON.stringify(draft));
  } catch {
    // Storage unavailable: the inputs simply are not kept across reloads.
  }
}

/**
 * Removes one shipment's entry from a keyed input map (after a successful submit).
 *
 * @param inputs - Keyed inputs.
 * @param shipmentId - Shipment whose entry to drop.
 * @returns A new map without that entry.
 */
export function withoutEntry(inputs: Record<string, string>, shipmentId: string): Record<string, string> {
  const next = Object.assign({}, inputs);
  delete next[shipmentId];
  return next;
}

/** Minimum gap between two automatic refreshes when the rider returns to the app (ms). */
export const FOCUS_REFETCH_MIN_INTERVAL_MS = 30_000;

/** Shown when an exception has no recorded NDR reason. */
const NDR_REASON_FALLBACK_LABEL = "Exception";

/**
 * Human label of a booked service type ("Surface (Truck)" instead of `SURFACE_ROAD`).
 *
 * @param serviceType - Raw `ServiceType` value from the API.
 * @returns The Delhivery-style label, or the raw value when it is not mapped.
 */
export function serviceTypeLabel(serviceType: string | null | undefined): string {
  return getOptionMeta(SERVICE_TYPE_OPTIONS, serviceType)?.label ?? serviceType ?? "";
}

/**
 * Human label of an NDR reason ("Consignee not available" instead of `CONSIGNEE_UNAVAILABLE`).
 *
 * @param reason - Raw `NdrExceptionReason` value, or null when none was recorded.
 * @returns The Delhivery One wording, the raw value when unmapped, or "Exception".
 */
export function ndrReasonLabel(reason: string | null | undefined): string {
  return getOptionMeta(NDR_REASON_OPTIONS, reason)?.label ?? reason ?? NDR_REASON_FALLBACK_LABEL;
}

/** Pickup-tab filter value for "still to be picked up" (Scheduled + Out for pickup). */
export const PICKUP_FILTER_ACTIVE = "ACTIVE";
/** Pickup-tab filter value for every pickup request. */
export const PICKUP_FILTER_ALL = "ALL";

/** Pickup request statuses that still need a field visit. */
const ACTIVE_PICKUP_STATUSES: ReadonlySet<ManifestStatus> = new Set([
  ManifestStatus.SCHEDULED,
  ManifestStatus.OUT_FOR_PICKUP,
]);

/**
 * Whether a pickup request matches the First-Mile tab's status filter.
 *
 * @param status - Pickup request status from the API.
 * @param filter - `PICKUP_FILTER_ACTIVE`, `PICKUP_FILTER_ALL` or one `ManifestStatus`.
 * @returns True when the card should be listed.
 */
export function matchesPickupFilter(status: ManifestStatus, filter: string): boolean {
  if (filter === PICKUP_FILTER_ALL) return true;
  if (filter === PICKUP_FILTER_ACTIVE) return ACTIVE_PICKUP_STATUSES.has(status);
  return status === filter;
}

/**
 * Parses the rider's "Actual pieces" input: a whole number of at least 1, else null.
 *
 * @param raw - Text typed on the pickup card (may be empty).
 * @returns The piece count, or null when blank / invalid (the booked count then applies).
 */
export function parseActualPieces(raw: string | null | undefined): number | null {
  const text = (raw ?? "").trim();
  if (text === "") return null;
  const count = Number(text);
  return Number.isInteger(count) && count >= 1 ? count : null;
}

/**
 * Box count text for the "Picked N of M?" confirmation, showing the rider's actual pieces.
 *
 * @param bookedCount - Boxes booked by the seller (`package_count`).
 * @param actualRaw - What the rider typed in "Actual pieces" for this AWB.
 * @returns e.g. "1 box", "3 boxes" or "2 boxes (booked 1)".
 */
export function pickedBoxesLabel(
  bookedCount: number | null | undefined,
  actualRaw: string | null | undefined
): string {
  const booked = bookedCount ?? 1;
  const actual = parseActualPieces(actualRaw);
  const shown = actual ?? booked;
  const text = `${shown} ${shown === 1 ? "box" : "boxes"}`;
  return actual !== null && actual !== booked ? `${text} (booked ${booked})` : text;
}
