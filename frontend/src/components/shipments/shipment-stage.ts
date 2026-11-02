// frontend/src/components/shipments/shipment-stage.ts
/**
 * The ONE status -> stage map for the shipment detail pages (B2C `/shipments/[id]` and
 * B2B `/b2b/shipments/[id]`), audit item D-02.
 *
 * Every `PickupStatus` says how far the 6-step tracking stepper has got, whether the
 * parcel has left the seller (picked up), whether it is on the forward or the RTO leg,
 * and whether the closing step ("Delivered", "RTO ...", "Lost", "Cancelled", ...) has
 * been reached. Mirrors Delhivery One's order stepper (help center `track-orders`).
 *
 * Display only: the backend `ShipmentLifecycleMachine` stays the status authority.
 * Badge wording comes from `getShipmentStatusLabel` and badge tints from the shared
 * `PICKUP_STATUS_OPTIONS` tones, so the detail pages never print a raw enum.
 */
import { PickupStatus } from "@/api_client";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import { PICKUP_STATUS_OPTIONS, type OptionTone } from "@/lib/form-options";

/** Steps of the detail-page stepper, in the order they are reached. */
export enum ShipmentStepperStage {
  MANIFESTED = 0,
  READY_TO_SHIP = 1,
  PICKUP_SCHEDULED = 2,
  IN_TRANSIT = 3,
  OUT_FOR_DELIVERY = 4,
}

/** Which leg the parcel is on. */
export enum ShipmentTrack {
  FORWARD = "FORWARD",
  RTO = "RTO",
}

/** Stage facts for one shipment status. */
export interface ShipmentStageInfo {
  /** Furthest progress step reached on the stepper (the closing step is `isClosed`). */
  stage: ShipmentStepperStage;
  /** Forward leg, or Return to Origin. */
  track: ShipmentTrack;
  /** Whether the closing step of the stepper is reached (delivered, returned, lost, closed). */
  isClosed: boolean;
}

/** Shorthand for the map rows below. */
function _stage(
  stage: ShipmentStepperStage,
  track: ShipmentTrack,
  isClosed: boolean,
): ShipmentStageInfo {
  return { stage, track, isClosed };
}

const { FORWARD, RTO } = ShipmentTrack;
const S = ShipmentStepperStage;

/**
 * Status -> stage. A `Record` over the enum, so a new `PickupStatus` fails to compile
 * until it is mapped here.
 *
 * - RTO and Lost parcels were picked up and moved, so they sit at In-transit; whether
 *   they ever went out for delivery is not known from the status alone.
 * - Cancelled / QC failed / Rejected at pickup close the order before pickup.
 * - EXCEPTION (NDR) keeps the existing behaviour: shown on the In-transit step.
 */
export const SHIPMENT_STAGE_BY_STATUS: Readonly<Record<PickupStatus, ShipmentStageInfo>> = {
  [PickupStatus.DRAFT]: _stage(S.MANIFESTED, FORWARD, false),
  [PickupStatus.OPEN]: _stage(S.READY_TO_SHIP, FORWARD, false),
  [PickupStatus.ASSIGNED]: _stage(S.PICKUP_SCHEDULED, FORWARD, false),
  [PickupStatus.IN_TRANSIT]: _stage(S.IN_TRANSIT, FORWARD, false),
  [PickupStatus.OUT_FOR_DELIVERY]: _stage(S.OUT_FOR_DELIVERY, FORWARD, false),
  [PickupStatus.EXCEPTION]: _stage(S.IN_TRANSIT, FORWARD, false),
  [PickupStatus.COMPLETED]: _stage(S.OUT_FOR_DELIVERY, FORWARD, true),
  [PickupStatus.CANCELLED]: _stage(S.MANIFESTED, FORWARD, true),
  [PickupStatus.RTO_INITIATED]: _stage(S.IN_TRANSIT, RTO, true),
  [PickupStatus.RTO_IN_TRANSIT]: _stage(S.IN_TRANSIT, RTO, true),
  [PickupStatus.RTO_DELIVERED]: _stage(S.IN_TRANSIT, RTO, true),
  [PickupStatus.QC_FAILED]: _stage(S.MANIFESTED, FORWARD, true),
  [PickupStatus.REJECTED_AT_PICKUP]: _stage(S.MANIFESTED, FORWARD, true),
  [PickupStatus.LOST]: _stage(S.IN_TRANSIT, FORWARD, true),
};

/** Label of the closing step while it has not been reached yet. */
const PENDING_CLOSING_STEP_LABEL = "Delivered";

/** Badge classes per shared status tone (status palettes plus the runtime `primary` token). */
const STATUS_BADGE_CLASSES: Readonly<Record<OptionTone, string>> = {
  neutral: "bg-slate-100 text-slate-700 border-slate-200",
  brand: "bg-primary/20 text-primary border-primary/30",
  sky: "bg-sky-100 text-sky-700 border-sky-200",
  amber: "bg-amber-100 text-amber-700 border-amber-200",
  emerald: "bg-emerald-100 text-emerald-700 border-emerald-200",
  rose: "bg-rose-100 text-rose-700 border-rose-200",
};

/**
 * Returns the stage facts for a status.
 *
 * @param status - Current shipment status.
 * @returns The `SHIPMENT_STAGE_BY_STATUS` row.
 */
export function getShipmentStage(status: PickupStatus): ShipmentStageInfo {
  return SHIPMENT_STAGE_BY_STATUS[status];
}

/**
 * Whether a progress step of the stepper is ticked for this status.
 *
 * @param status - Current shipment status.
 * @param step - Progress step to test.
 * @returns True when the status has reached `step`.
 */
export function isStepperStageReached(
  status: PickupStatus,
  step: ShipmentStepperStage,
): boolean {
  return getShipmentStage(status).stage >= step;
}

/**
 * Whether the parcel has been picked up from the seller (In-transit step ticked).
 *
 * @param status - Current shipment status.
 * @returns True for In transit, Out for delivery, NDR, Delivered, every RTO state and Lost.
 */
export function isShipmentPickedUp(status: PickupStatus): boolean {
  return isStepperStageReached(status, ShipmentStepperStage.IN_TRANSIT);
}

/**
 * Whether the parcel is on the Return to Origin leg.
 *
 * @param status - Current shipment status.
 * @returns True for RTO Initiated, RTO In Transit and RTO Delivered.
 */
export function isRtoTrack(status: PickupStatus): boolean {
  return getShipmentStage(status).track === ShipmentTrack.RTO;
}

/**
 * Label of the stepper's closing step: the outcome once reached ("Delivered",
 * "RTO In Transit", "Lost", "Cancelled", ...), otherwise the pending "Delivered".
 *
 * @param status - Current shipment status.
 * @returns Delhivery-style label for the last step.
 */
export function getClosingStepLabel(status: PickupStatus): string {
  return getShipmentStage(status).isClosed
    ? getShipmentStatusLabel(status)
    : PENDING_CLOSING_STEP_LABEL;
}

/**
 * Badge classes for the detail-page status badge, from the shared status tone.
 *
 * @param status - Current shipment status.
 * @returns Tailwind classes (background, text, border).
 */
export function getShipmentStatusBadgeClass(status: PickupStatus): string {
  return STATUS_BADGE_CLASSES[PICKUP_STATUS_OPTIONS[status].tone];
}
