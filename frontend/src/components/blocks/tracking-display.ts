// frontend/src/components/blocks/tracking-display.ts
/**
 * Display-only helpers for the PUBLIC tracking page (F-01, F-09).
 *
 * - `buildPublicTrackingSteps`: the buyer-facing 5-step stepper
 *   (Booked → Picked up → In transit → Out for delivery → Delivered/outcome),
 *   derived from the shared status → stage map in `shipment-stage.ts`, so a
 *   parcel that is still waiting for pickup never shows as moved.
 * - `friendlyActivityTitle`: turns raw timeline titles such as
 *   `Status: OUT_FOR_DELIVERY` into "Out for delivery".
 * - `normalizeTrackingId`: trims and upper-cases what the buyer typed.
 *
 * The backend `ShipmentLifecycleMachine` stays the status authority; nothing
 * here computes money or business rules.
 */
import { ApiError, NdrExceptionReason, PickupStatus } from "@/api_client";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import {
  ShipmentStepperStage,
  getClosingStepLabel,
  getShipmentStage,
  isShipmentPickedUp,
  isStepperStageReached,
} from "@/components/shipments/shipment-stage";
import { NDR_REASON_OPTIONS } from "@/lib/form-options";

/** Visual tone of a stepper step. */
export enum TrackingStepTone {
  /** Normal progress (brand colour once reached). */
  PROGRESS = "PROGRESS",
  /** A closing outcome that is not a delivery (RTO, lost, cancelled...). */
  ALERT = "ALERT",
}

/** One step of the public tracking stepper. */
export interface PublicTrackingStep {
  label: string;
  reached: boolean;
  tone: TrackingStepTone;
}

/** Statuses whose closing step is a normal, successful delivery. */
const SUCCESSFUL_CLOSING_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.COMPLETED,
]);

/**
 * Consumer-friendly status labels for the public tracking badge and closing step.
 * Avoids internal staff jargon ("RTO Initiated", "Exception (NDR)", "Ready to Ship")
 * and ensures an RTO parcel always reads "Returning to seller" / "Returned to seller",
 * never "Delivered".
 */
const PUBLIC_STATUS_LABELS: Readonly<Record<PickupStatus, string>> = {
  [PickupStatus.DRAFT]: "Order placed",
  [PickupStatus.OPEN]: "Order placed",
  [PickupStatus.ASSIGNED]: "Pickup scheduled",
  [PickupStatus.IN_TRANSIT]: "In transit",
  [PickupStatus.OUT_FOR_DELIVERY]: "Out for delivery",
  [PickupStatus.COMPLETED]: "Delivered",
  [PickupStatus.EXCEPTION]: "Shipment on hold",
  [PickupStatus.RTO_INITIATED]: "Returning to seller",
  [PickupStatus.RTO_IN_TRANSIT]: "Returning to seller",
  [PickupStatus.RTO_DELIVERED]: "Returned to seller",
  [PickupStatus.CANCELLED]: "Cancelled",
  [PickupStatus.LOST]: "Under investigation",
  [PickupStatus.QC_FAILED]: "Pickup not completed",
  [PickupStatus.REJECTED_AT_PICKUP]: "Pickup not completed",
};

/**
 * Returns the consumer-facing status label for the public tracking page.
 *
 * @param status - Raw `PickupStatus` from the public tracking API.
 * @returns Friendly consumer wording (e.g. "Returning to seller" for `RTO_INITIATED`).
 */
export function getPublicStatusLabel(status: PickupStatus): string {
  return PUBLIC_STATUS_LABELS[status] ?? getShipmentStatusLabel(status);
}

/** Matches one `Status: <ENUM>` fragment written by the backend activity log. */
const STATUS_FRAGMENT_PATTERN = /^Status:\s*([A-Z_]+)$/;
/** Matches one `Exception Raised: <ENUM>` fragment written by the backend activity log. */
const EXCEPTION_FRAGMENT_PATTERN = /^Exception Raised:\s*([A-Z_]+)$/;
/** Separator the backend uses to join several summary fragments. */
const SUMMARY_SEPARATOR = ", ";

const PICKUP_STATUS_VALUES: ReadonlySet<string> = new Set(Object.values(PickupStatus));
const NDR_REASON_VALUES: ReadonlySet<string> = new Set(Object.values(NdrExceptionReason));

/**
 * Builds the buyer-facing stepper for a shipment status.
 *
 * @param status - Current shipment status from the public tracking API.
 * @returns Five steps in display order, each with its reached flag and tone.
 */
export function buildPublicTrackingSteps(status: PickupStatus): PublicTrackingStep[] {
  const pickedUp = isShipmentPickedUp(status);
  const closed = getShipmentStage(status).isClosed;
  const closingTone =
    closed && !SUCCESSFUL_CLOSING_STATUSES.has(status)
      ? TrackingStepTone.ALERT
      : TrackingStepTone.PROGRESS;
  return [
    { label: "Booked", reached: true, tone: TrackingStepTone.PROGRESS },
    { label: "Picked up", reached: pickedUp, tone: TrackingStepTone.PROGRESS },
    { label: "In transit", reached: pickedUp, tone: TrackingStepTone.PROGRESS },
    {
      label: "Out for delivery",
      reached: isStepperStageReached(status, ShipmentStepperStage.OUT_FOR_DELIVERY),
      tone: TrackingStepTone.PROGRESS,
    },
    {
      label: closed ? getPublicStatusLabel(status) : getClosingStepLabel(status),
      reached: closed,
      tone: closingTone,
    },
  ];
}

/**
 * Index of the last step reached WITHOUT a gap from the first one, used to
 * draw the progress line (a cancelled-before-pickup order fills nothing).
 *
 * @param steps - Steps from `buildPublicTrackingSteps`.
 * @returns Zero-based index (0 when only "Booked" is reached).
 */
export function contiguousProgressIndex(steps: readonly PublicTrackingStep[]): number {
  let index = 0;
  while (index + 1 < steps.length && steps[index + 1].reached) index += 1;
  return index;
}

/**
 * Replaces one raw backend summary fragment with buyer-friendly wording.
 *
 * @param fragment - e.g. `Status: OUT_FOR_DELIVERY` or `Exception Raised: CONSIGNEE_REFUSED`.
 * @returns The friendly text, or the fragment unchanged when it is not raw.
 */
function _friendlyFragment(fragment: string): string {
  const statusMatch = STATUS_FRAGMENT_PATTERN.exec(fragment);
  if (statusMatch && PICKUP_STATUS_VALUES.has(statusMatch[1])) {
    return getShipmentStatusLabel(statusMatch[1] as PickupStatus);
  }
  const exceptionMatch = EXCEPTION_FRAGMENT_PATTERN.exec(fragment);
  if (exceptionMatch && NDR_REASON_VALUES.has(exceptionMatch[1])) {
    const reason = NDR_REASON_OPTIONS[exceptionMatch[1] as NdrExceptionReason];
    return `Delivery issue: ${reason.label}`;
  }
  if (PICKUP_STATUS_VALUES.has(fragment)) {
    return getShipmentStatusLabel(fragment as PickupStatus);
  }
  return fragment;
}

/**
 * Makes a public timeline title readable (`Status: COMPLETED` → "Delivered").
 *
 * @param title - `status_title` from the public tracking API.
 * @returns The title with every raw enum fragment replaced by its label.
 */
export function friendlyActivityTitle(title: string): string {
  return title
    .split(SUMMARY_SEPARATOR)
    .map((fragment) => _friendlyFragment(fragment.trim()))
    .join(SUMMARY_SEPARATOR);
}

/**
 * Normalises a typed tracking number: trims it, drops inner spaces and
 * upper-cases it (AWBs are issued in upper case, e.g. `NAV-A1B2C3D4`).
 *
 * @param raw - Text from the search box or the URL.
 * @returns The normalised ID ("" when nothing usable was typed).
 */
export function normalizeTrackingId(raw: string | null | undefined): string {
  return (raw ?? "").replace(/\s+/g, "").toUpperCase();
}

/** Neutral search placeholder: no brand or sample AWB that could pass for a real one. */
export const TRACKING_INPUT_PLACEHOLDER = "Enter AWB / tracking number";

/** HTTP status the tracking API returns for an unknown AWB in this tenant. */
const HTTP_NOT_FOUND = 404;

/** Why tracking could not be shown. */
export enum TrackingLoadError {
  /** The AWB does not exist in this workspace: show tips, no retry. */
  NOT_FOUND = "NOT_FOUND",
  /** Network/server hiccup: offer a retry. */
  UNAVAILABLE = "UNAVAILABLE",
}

/**
 * Maps a failed tracking call to the state shown to the buyer, so a slow or
 * failing backend is never reported as "Shipment Not Found" (F-09).
 *
 * @param err - Error thrown by `TrackingService.trackShipment`.
 * @returns NOT_FOUND only for a real 404; everything else is retryable.
 */
export function classifyTrackingError(err: unknown): TrackingLoadError {
  return err instanceof ApiError && err.status === HTTP_NOT_FOUND
    ? TrackingLoadError.NOT_FOUND
    : TrackingLoadError.UNAVAILABLE;
}
