// frontend/src/components/pickups/pickup-row-parts.tsx
"use client";

/**
 * Presentational building blocks shared by the Pickup Requests table and its
 * mobile card layout: Pickup ID link, date & slot, location, status cell and
 * the per-row action buttons.
 */
import { ManifestResponse, ManifestStatus, ServiceFlow } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import {
  CalendarClock,
  ChevronDown,
  Download,
  Info,
  MoreHorizontal,
  Printer,
} from "lucide-react";
import { toast } from "sonner";

import {
  formatPickupDate,
  getPickupDisplayId,
  getPickupSlotLabel,
  PICKUP_FLOW_CONFIG,
  PickupLabelFormat,
} from "./pickup-constants";
import { getManifestStatusDisplay } from "./status-display";

/** Statuses that still allow cancellation / ops outcomes (mirrors the backend rules). */
const ACTIVE_PICKUP_STATUSES: readonly ManifestStatus[] = [
  ManifestStatus.SCHEDULED,
  ManifestStatus.OUT_FOR_PICKUP,
];

/** Callbacks for every row action; the list component owns the API calls. */
export interface PickupRowHandlers {
  onPrintLabel: (manifest: ManifestResponse, labelFormat: PickupLabelFormat) => void;
  onManifestCopy: (manifest: ManifestResponse) => void;
  onCancel: (manifest: ManifestResponse) => void;
  onReschedule: (manifest: ManifestResponse) => void;
  onOutForPickup: (manifest: ManifestResponse) => void;
  onMarkPicked: (manifest: ManifestResponse) => void;
  onNotPicked: (manifest: ManifestResponse) => void;
}

/** Context every row part needs. */
export interface PickupRowContext {
  flow: ServiceFlow;
  /** Carrier ops outcomes (out for pickup / picked / not picked): `capabilities.canOperate`. */
  canOperate: boolean;
  /** Cancel a pickup request: `capabilities.canBook`. */
  canBook: boolean;
  handlers: PickupRowHandlers;
  /** Id of the row whose action is in flight (disables its buttons). */
  busyId: string | null;
}

/**
 * Whether a pickup is still open for cancellation / ops outcomes.
 *
 * @param status - Pickup Request status.
 * @returns True for SCHEDULED and OUT_FOR_PICKUP.
 */
export function isActivePickup(status: ManifestStatus): boolean {
  return ACTIVE_PICKUP_STATUSES.includes(status);
}

/**
 * Whether the pickup has linked shipments whose labels can be printed.
 *
 * @param manifest - Pickup Request row.
 * @returns False for blind pickups and empty pickups.
 */
function _hasPrintableLabels(manifest: ManifestResponse): boolean {
  return !manifest.is_blind_pickup && (manifest.expected_awbs ?? 0) > 0;
}

/** Link-coloured 9-digit Pickup ID; click copies it to the clipboard. */
export function PickupIdLink({ manifest }: { manifest: ManifestResponse }) {
  const displayId = getPickupDisplayId(manifest);
  return (
    <button
      type="button"
      title="Copy Pickup ID"
      onClick={(event) => {
        event.stopPropagation();
        void navigator.clipboard
          ?.writeText(displayId)
          .then(() => toast.success(`Pickup ID ${displayId} copied`))
          .catch(() => undefined);
      }}
      className="font-mono text-sm font-semibold text-primary hover:underline underline-offset-4"
    >
      {displayId}
    </button>
  );
}

/** Pickup date (line 1) and Delhivery-style slot (line 2). */
export function PickupDateSlot({ manifest }: { manifest: ManifestResponse }) {
  return (
    <div className="flex flex-col">
      <span className="text-sm font-medium text-foreground">
        {formatPickupDate(manifest.scheduled_date)}
      </span>
      <span className="text-xs text-muted-foreground">{getPickupSlotLabel(manifest.time_slot)}</span>
    </div>
  );
}

/** Bold uppercase location name (line 1) and truncated address (line 2). */
export function PickupLocationCell({ manifest }: { manifest: ManifestResponse }) {
  return (
    <div className="flex flex-col min-w-0 max-w-[260px]">
      <span className="text-sm font-semibold uppercase text-foreground truncate">
        {manifest.pickup_location_name || "-"}
      </span>
      <span
        className="text-xs uppercase text-muted-foreground truncate"
        title={manifest.pickup_location_address || undefined}
      >
        {manifest.pickup_location_address || "-"}
      </span>
    </div>
  );
}

/** Neutral pill used for AWB / LRN counters. */
function CounterPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-foreground">
      {children}
    </span>
  );
}

/** Status chip plus Delhivery sub-line (picked counter or failure reason). */
export function PickupStatusCell({
  manifest,
  flow,
}: {
  manifest: ManifestResponse;
  flow: ServiceFlow;
}) {
  const display = getManifestStatusDisplay(manifest.status);
  const noun = PICKUP_FLOW_CONFIG[flow].shipmentNoun;
  const expected = manifest.expected_awbs ?? 0;
  const picked = manifest.picked_awbs ?? 0;
  const isNotPicked = manifest.status === ManifestStatus.NOT_PICKED;

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge
          variant="outline"
          className={cn("rounded-md px-2 py-0.5 text-[11px] font-semibold shadow-none", display.badgeClass)}
        >
          {isNotPicked && <Info className="h-3 w-3" />}
          {display.label}
        </Badge>
        {manifest.status === ManifestStatus.PICKED && (
          <CounterPill>
            {picked}/{expected} {noun}s picked
          </CounterPill>
        )}
        {isActivePickup(manifest.status) && (
          <CounterPill>
            {manifest.is_blind_pickup
              ? `${manifest.total_boxes} boxes · Blind`
              : `${expected} ${noun}${expected === 1 ? "" : "s"}`}
          </CounterPill>
        )}
      </div>
      {isNotPicked && manifest.failure_reason && (
        <span className="max-w-[240px] text-xs text-muted-foreground">{manifest.failure_reason}</span>
      )}
    </div>
  );
}

/** "Print label" with an A4 / thermal 4x2 format choice. */
function PrintLabelButton({
  manifest,
  context,
}: {
  manifest: ManifestResponse;
  context: PickupRowContext;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={context.busyId === manifest.id}
          onClick={(event) => event.stopPropagation()}
          className="h-8 text-xs font-semibold"
        >
          <Printer className="mr-1.5 h-3.5 w-3.5" /> Print label
          <ChevronDown className="ml-1 h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() => context.handlers.onPrintLabel(manifest, PickupLabelFormat.A4)}
        >
          A4 labels
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => context.handlers.onPrintLabel(manifest, PickupLabelFormat.THERMAL_4X2)}
        >
          Thermal 4x2 labels
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Admin ops outcomes + B2B run-sheet, grouped in a compact overflow menu. */
function OpsMenu({ manifest, context }: { manifest: ManifestResponse; context: PickupRowContext }) {
  const { handlers, canOperate, flow } = context;
  const showRunSheet = flow === ServiceFlow.B2B;
  if (!canOperate && !showRunSheet) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="More pickup actions"
          disabled={context.busyId === manifest.id}
          onClick={(event) => event.stopPropagation()}
          className="h-8 w-8"
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {showRunSheet && (
          <DropdownMenuItem onClick={() => handlers.onManifestCopy(manifest)}>
            <Download className="mr-2 h-3.5 w-3.5" /> Driver run-sheet
          </DropdownMenuItem>
        )}
        {canOperate && (
          <>
            {showRunSheet && <DropdownMenuSeparator />}
            <DropdownMenuLabel className="text-xs text-muted-foreground">Pickup operations</DropdownMenuLabel>
            {manifest.status === ManifestStatus.SCHEDULED && (
              <DropdownMenuItem onClick={() => handlers.onOutForPickup(manifest)}>
                Out for pickup
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => handlers.onMarkPicked(manifest)}>
              Mark picked up
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => handlers.onNotPicked(manifest)}
              className="text-destructive focus:text-destructive"
            >
              Not picked
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Delhivery row actions by status (no "Raise a ticket": no support module yet). */
export function PickupRowActions({
  manifest,
  context,
}: {
  manifest: ManifestResponse;
  context: PickupRowContext;
}) {
  const { handlers } = context;
  const busy = context.busyId === manifest.id;

  if (isActivePickup(manifest.status)) {
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {_hasPrintableLabels(manifest) && <PrintLabelButton manifest={manifest} context={context} />}
        {context.canBook && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation();
              handlers.onCancel(manifest);
            }}
            className="h-8 text-xs font-semibold text-destructive hover:text-destructive hover:bg-destructive/10"
          >
            Cancel pickup
          </Button>
        )}
        <OpsMenu manifest={manifest} context={context} />
      </div>
    );
  }

  if (manifest.status === ManifestStatus.PICKED) {
    return (
      <Button
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={(event) => {
          event.stopPropagation();
          handlers.onManifestCopy(manifest);
        }}
        className="h-8 text-xs font-semibold"
      >
        Manifest Copy <Download className="ml-1.5 h-3.5 w-3.5" />
      </Button>
    );
  }

  if (manifest.status === ManifestStatus.NOT_PICKED) {
    return (
      <Button
        variant="secondary"
        size="sm"
        disabled={busy}
        onClick={(event) => {
          event.stopPropagation();
          handlers.onReschedule(manifest);
        }}
        className="h-8 text-xs font-semibold"
      >
        <CalendarClock className="mr-1.5 h-3.5 w-3.5" /> Reschedule
      </Button>
    );
  }

  return <span className="text-xs text-muted-foreground">-</span>;
}
