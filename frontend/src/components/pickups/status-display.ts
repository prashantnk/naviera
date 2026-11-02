// frontend/src/components/pickups/status-display.ts
/**
 * Display-only labels and badge styles for Pickup Request (manifest) and
 * shipment statuses, aligned with Delhivery One wording.
 *
 * The enum VALUES sent to / received from the API never change; only the
 * human-facing labels do (e.g. `OPEN` is shown as "Ready to Ship").
 *
 * Spring Boot analogy: a `MessageSource` bundle that maps enum constants to
 * localized UI strings without touching the persisted `@Enumerated` values.
 */
import { ManifestStatus, PickupStatus } from "@/api_client";
import {
  OptionMeta,
  PICKUP_STATUS_OPTIONS,
  SelectOption,
  toOptions,
  withAllOption,
} from "@/lib/form-options";
import { CalendarClock, CircleCheckBig, CircleX, Truck, TriangleAlert } from "lucide-react";

/** Visual metadata for one Pickup Request status. */
export interface ManifestStatusDisplay {
  /** Delhivery-style label, e.g. "Scheduled" or "Not Picked". */
  label: string;
  /** Semantic Tailwind classes for the status badge (no tenant brand hex). */
  badgeClass: string;
}

/** Pickup Request status -> label + badge styling. */
export const MANIFEST_STATUS_DISPLAY: Readonly<Record<ManifestStatus, ManifestStatusDisplay>> = {
  [ManifestStatus.SCHEDULED]: {
    label: "Scheduled",
    badgeClass: "bg-amber-50 text-amber-700 border-amber-200",
  },
  [ManifestStatus.OUT_FOR_PICKUP]: {
    label: "Out for Pickup",
    badgeClass: "bg-sky-50 text-sky-700 border-sky-200",
  },
  [ManifestStatus.PICKED]: {
    label: "Picked",
    badgeClass: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  [ManifestStatus.NOT_PICKED]: {
    label: "Not Picked",
    badgeClass: "bg-destructive/10 text-destructive border-destructive/20",
  },
  [ManifestStatus.CANCELED]: {
    label: "Cancelled",
    badgeClass: "bg-destructive/10 text-destructive border-destructive/20",
  },
};

/** Status filter order on the Pickup Requests list (Delhivery order). */
export const MANIFEST_STATUS_FILTER_ORDER: readonly ManifestStatus[] = [
  ManifestStatus.SCHEDULED,
  ManifestStatus.OUT_FOR_PICKUP,
  ManifestStatus.PICKED,
  ManifestStatus.NOT_PICKED,
  ManifestStatus.CANCELED,
];

/**
 * Delhivery wording for the pre-pickup shipment states. Every other status
 * falls back to the shared `PICKUP_STATUS_OPTIONS` metadata.
 */
const SHIPMENT_STATUS_LABEL_OVERRIDES: Readonly<Partial<Record<PickupStatus, string>>> = {
  [PickupStatus.OPEN]: "Ready to Ship",
  [PickupStatus.ASSIGNED]: "Ready for Pickup",
};

/**
 * Returns the human-facing label for a shipment status.
 *
 * @param status - Raw `PickupStatus` enum value from the API.
 * @returns Delhivery-style label (e.g. "Ready to Ship" for `OPEN`).
 */
export function getShipmentStatusLabel(status: PickupStatus): string {
  const override = SHIPMENT_STATUS_LABEL_OVERRIDES[status];
  if (override) return override;
  const meta = PICKUP_STATUS_OPTIONS[status];
  return meta ? meta.label : String(status).replace(/_/g, " ");
}

/**
 * Returns the display metadata for a Pickup Request status.
 *
 * @param status - Raw `ManifestStatus` enum value from the API.
 * @returns Label and badge classes; unknown values degrade to a neutral badge.
 */
export function getManifestStatusDisplay(status: ManifestStatus): ManifestStatusDisplay {
  return (
    MANIFEST_STATUS_DISPLAY[status] ?? {
      label: String(status).replace(/_/g, " "),
      badgeClass: "bg-muted text-muted-foreground border-border",
    }
  );
}

/**
 * Whether a shipment can be added to a Pickup Request from the Shipments list.
 * Only `OPEN` ("Ready to Ship") shipments are linkable; the server re-validates.
 *
 * @param status - Raw `PickupStatus` enum value.
 * @returns True when the row should show a selection checkbox.
 */
export function isShipmentPickupSelectable(status: PickupStatus): boolean {
  return status === PickupStatus.OPEN;
}

/** IconSelect metadata for Pickup Request statuses (labels mirror `MANIFEST_STATUS_DISPLAY`). */
export const MANIFEST_STATUS_OPTIONS: Readonly<Record<ManifestStatus, OptionMeta>> = {
  [ManifestStatus.SCHEDULED]: {
    label: MANIFEST_STATUS_DISPLAY[ManifestStatus.SCHEDULED].label,
    description: "Booked and waiting for the pickup slot",
    icon: CalendarClock,
    tone: "amber",
  },
  [ManifestStatus.OUT_FOR_PICKUP]: {
    label: MANIFEST_STATUS_DISPLAY[ManifestStatus.OUT_FOR_PICKUP].label,
    description: "Pickup executive is on the way",
    icon: Truck,
    tone: "sky",
  },
  [ManifestStatus.PICKED]: {
    label: MANIFEST_STATUS_DISPLAY[ManifestStatus.PICKED].label,
    description: "Shipments collected from the location",
    icon: CircleCheckBig,
    tone: "emerald",
  },
  [ManifestStatus.NOT_PICKED]: {
    label: MANIFEST_STATUS_DISPLAY[ManifestStatus.NOT_PICKED].label,
    description: "Pickup failed · reschedule it",
    icon: TriangleAlert,
    tone: "rose",
  },
  [ManifestStatus.CANCELED]: {
    label: MANIFEST_STATUS_DISPLAY[ManifestStatus.CANCELED].label,
    description: "Cancelled before pickup",
    icon: CircleX,
    tone: "rose",
  },
};

/** Status filter options for the Pickup Requests list ("All statuses" first). */
export const MANIFEST_STATUS_FILTER_OPTIONS = withAllOption(
  toOptions(MANIFEST_STATUS_OPTIONS, MANIFEST_STATUS_FILTER_ORDER),
  "All statuses"
);

/**
 * Status filter options for the Shipments lists, using the Delhivery wording
 * ("Ready to Ship" / "Ready for Pickup") on top of the shared metadata.
 */
export const SHIPMENT_STATUS_FILTER_OPTIONS = withAllOption(
  toOptions(PICKUP_STATUS_OPTIONS).map(
    (option): SelectOption<PickupStatus> =>
      Object.assign({}, option, { label: getShipmentStatusLabel(option.value) })
  ),
  "All Statuses"
);
