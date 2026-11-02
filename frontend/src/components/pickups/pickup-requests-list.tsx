// frontend/src/components/pickups/pickup-requests-list.tsx
"use client";

/**
 * Flow-aware Pickup Requests list (Delhivery One "Pickup Requests" parity),
 * used by both `/pickup-requests` (B2C) and `/b2b/pickup-requests` (B2B).
 *
 * Layout: header (icon tile, title, subtitle, "Create pickup request +") ·
 * filters (Search Pickup ID · Pickup date range · Pickup location · Status) ·
 * table on desktop / cards on mobile · status-driven row actions.
 *
 * Spring Boot analogy: a Thymeleaf fragment parameterised by `serviceFlow`
 * that renders the same view for two `@RequestMapping`s.
 */
import { ManifestResponse, ManifestsService, ManifestStatus, ServiceFlow } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { DataTable } from "@/components/ui/data-table";
import { IconSelect } from "@/components/ui/icon-select";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ALL_FILTER_VALUE } from "@/lib/form-options";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import { format } from "date-fns";
import { CalendarRange, ChevronDown, Loader2, Plus, Printer, Search, Truck, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { DateRange } from "react-day-picker";
import { toast } from "sonner";

import {
  ConfirmPickupDialog,
  DispatchPickupDialog,
  NotPickedDialog,
} from "./pickup-action-dialogs";
import {
  API_DATE_FORMAT,
  buildCreatePickupHref,
  getPickupDisplayId,
  nextWorkingApiDate,
  PICKUP_FLOW_CONFIG,
  PICKUP_PAGE_SUBTITLE,
  PICKUP_PAGE_TITLE,
  PickupLabelFormat,
} from "./pickup-constants";
import { downloadPickupLabels, downloadPickupManifestCopy } from "./pickup-downloads";
import { getPickupRequestColumns } from "./pickup-request-columns";
import {
  PickupDateSlot,
  PickupIdLink,
  PickupLocationCell,
  PickupRowActions,
  PickupRowContext,
  PickupRowHandlers,
  PickupStatusCell,
} from "./pickup-row-parts";
import { MANIFEST_STATUS_FILTER_OPTIONS } from "./status-display";

/** Select sentinel for "no filter" (shared with `withAllOption`). */
const ALL_VALUE = ALL_FILTER_VALUE;
/** Display format of the date range trigger. */
const RANGE_LABEL_FORMAT = "dd MMM";

/** Confirmable operations and their dialog copy. */
enum ConfirmKind {
  CANCEL = "CANCEL",
  OUT_FOR_PICKUP = "OUT_FOR_PICKUP",
  MARK_PICKED = "MARK_PICKED",
}

interface ConfirmCopy {
  title: (pickupId: string) => string;
  description: string;
  confirmLabel: string;
  destructive: boolean;
  success: (pickupId: string) => string;
}

const CONFIRM_COPY: Readonly<Record<ConfirmKind, ConfirmCopy>> = {
  [ConfirmKind.CANCEL]: {
    title: (pickupId) => `Cancel pickup ${pickupId}?`,
    description: "Its shipments go back to Ready to Ship and can be added to another pickup.",
    confirmLabel: "Cancel pickup",
    destructive: true,
    success: (pickupId) => `Pickup ${pickupId} cancelled. Its shipments are back in Ready to Ship.`,
  },
  [ConfirmKind.OUT_FOR_PICKUP]: {
    title: (pickupId) => `Mark ${pickupId} as Out for Pickup?`,
    description: "Use this once a pickup executive has been dispatched to the location.",
    confirmLabel: "Out for pickup",
    destructive: false,
    success: (pickupId) => `Pickup ${pickupId} is out for pickup.`,
  },
  [ConfirmKind.MARK_PICKED]: {
    title: (pickupId) => `Mark ${pickupId} as Picked?`,
    description: "All linked shipments move to In Transit and receive their delivery OTPs.",
    confirmLabel: "Mark picked up",
    destructive: false,
    success: (pickupId) => `Pickup ${pickupId} marked as picked.`,
  },
};

interface PendingConfirm {
  kind: ConfirmKind;
  manifest: ManifestResponse;
}

/**
 * Runs the API call for a confirmed operation.
 *
 * @param kind - Operation to execute.
 * @param manifestId - Pickup Request id.
 * @param tenantSlug - Current tenant slug header.
 * @returns The updated Pickup Request.
 */
function _runConfirmedAction(
  kind: ConfirmKind,
  manifestId: string,
  tenantSlug: string
): Promise<ManifestResponse> {
  if (kind === ConfirmKind.CANCEL) return ManifestsService.cancelManifest(manifestId, tenantSlug);
  if (kind === ConfirmKind.OUT_FOR_PICKUP) {
    return ManifestsService.markManifestOutForPickup(manifestId, tenantSlug);
  }
  return ManifestsService.dispatchManifest(manifestId, tenantSlug);
}

/**
 * Whether a pickup's date falls within the selected (inclusive) range.
 *
 * @param scheduledDate - API `yyyy-MM-dd` date.
 * @param range - Selected range (either end optional).
 * @returns True when no range is set or the date is inside it.
 */
function _isWithinRange(scheduledDate: string, range: DateRange | undefined): boolean {
  if (!range?.from) return true;
  const from = format(range.from, API_DATE_FORMAT);
  const to = format(range.to ?? range.from, API_DATE_FORMAT);
  return scheduledDate >= from && scheduledDate <= to;
}

/** Label of the date range filter trigger. */
function _rangeLabel(range: DateRange | undefined): string {
  if (!range?.from) return "Pickup date range";
  const from = format(range.from, RANGE_LABEL_FORMAT);
  return range.to ? `${from} - ${format(range.to, RANGE_LABEL_FORMAT)}` : from;
}

/** Props of the shared list. */
export interface PickupRequestsListProps {
  serviceFlow: ServiceFlow;
}

export function PickupRequestsList({ serviceFlow }: PickupRequestsListProps) {
  const router = useRouter();
  const { tenantSlug, routeTo } = useTenant();
  const { capabilities } = useUser();
  const flowConfig = PICKUP_FLOW_CONFIG[serviceFlow];

  const [manifests, setManifests] = useState<ManifestResponse[]>([]);
  const [loadedRequestKey, setLoadedRequestKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>(ALL_VALUE);
  const [locationFilter, setLocationFilter] = useState<string>(ALL_VALUE);
  const [dateRange, setDateRange] = useState<DateRange | undefined>(undefined);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  const [notPickedTarget, setNotPickedTarget] = useState<ManifestResponse | null>(null);
  const [dispatchTarget, setDispatchTarget] = useState<ManifestResponse | null>(null);
  const [dialogSubmitting, setDialogSubmitting] = useState(false);

  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  // Loading is derived: the list is loading until the current request key has completed.
  const requestKey = `${serviceFlow}|${statusFilter}|${tenantSlug}|${refreshKey}`;
  const loading = loadedRequestKey !== requestKey;

  useEffect(() => {
    let ignore = false;
    const status = statusFilter === ALL_VALUE ? null : (statusFilter as ManifestStatus);
    ManifestsService.listManifests(serviceFlow, status, null, tenantSlug)
      .then((rows) => {
        if (ignore) return;
        setManifests(rows);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!ignore) setError(extractApiErrorMessage(err, "Failed to load pickup requests."));
      })
      .finally(() => {
        if (!ignore) setLoadedRequestKey(requestKey);
      });
    return () => {
      ignore = true;
    };
  }, [serviceFlow, statusFilter, tenantSlug, requestKey]);

  const locationNames = useMemo(() => {
    const names = new Set(manifests.map((m) => m.pickup_location_name).filter(Boolean));
    return Array.from(names) as string[];
  }, [manifests]);

  const visibleManifests = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return manifests.filter((m) => {
      if (query && !getPickupDisplayId(m).toLowerCase().includes(query)) return false;
      if (locationFilter !== ALL_VALUE && m.pickup_location_name !== locationFilter) return false;
      return _isWithinRange(m.scheduled_date, dateRange);
    });
  }, [manifests, searchTerm, locationFilter, dateRange]);

  const handlers: PickupRowHandlers = useMemo(
    () => ({
      onPrintLabel: (manifest, labelFormat) => {
        setBusyId(manifest.id);
        downloadPickupLabels(manifest, labelFormat)
          .then(() => toast.success(`Labels for pickup ${getPickupDisplayId(manifest)} downloaded.`))
          .catch(() => toast.error("Failed to download labels."))
          .finally(() => setBusyId(null));
      },
      onManifestCopy: (manifest) => {
        setBusyId(manifest.id);
        downloadPickupManifestCopy(manifest)
          .then(() => toast.success(`Manifest copy for ${getPickupDisplayId(manifest)} downloaded.`))
          .catch(() => toast.error("Failed to download the manifest copy."))
          .finally(() => setBusyId(null));
      },
      onCancel: (manifest) => setPendingConfirm({ kind: ConfirmKind.CANCEL, manifest }),
      onOutForPickup: (manifest) => setPendingConfirm({ kind: ConfirmKind.OUT_FOR_PICKUP, manifest }),
      onMarkPicked: (manifest) => setDispatchTarget(manifest),
      onNotPicked: (manifest) => setNotPickedTarget(manifest),
      onReschedule: (manifest) =>
        router.push(
          routeTo(
            buildCreatePickupHref(serviceFlow, {
              locationId: manifest.pickup_address_id,
              locationName: manifest.pickup_location_name,
              date: nextWorkingApiDate(),
            })
          )
        ),
    }),
    [router, routeTo, serviceFlow]
  );

  const rowContext: PickupRowContext = useMemo(
    () => ({
      flow: serviceFlow,
      canOperate: capabilities.canOperate,
      canBook: capabilities.canBook,
      handlers,
      busyId,
    }),
    [serviceFlow, capabilities.canOperate, capabilities.canBook, handlers, busyId]
  );

  const toggleOne = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleMany = useCallback((ids: string[], checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  const columns = useMemo(
    () =>
      getPickupRequestColumns(rowContext, {
        selectedIds,
        onToggle: toggleOne,
        onToggleMany: toggleMany,
        isSelectable: () => true,
        rowNoun: "pickup request",
      }).map((col) => {
        if (col.id !== "actions") return col;
        return {
          ...col,
          cell: ({ row }: { row: { original: ManifestResponse } }) => {
            const manifest = row.original;
            const purId = getPickupDisplayId(manifest);
            const canConfirmPicked =
              capabilities.canOperate &&
              (manifest.status === ManifestStatus.SCHEDULED ||
                manifest.status === ManifestStatus.OUT_FOR_PICKUP);
            return (
              <div
                data-testid={`pickup-requests.row.${purId}`}
                className="flex flex-wrap items-center gap-1.5"
              >
                {canConfirmPicked && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busyId === manifest.id}
                    data-testid={`pickup-requests.row.${purId}.confirm-picked`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setDispatchTarget(manifest);
                    }}
                    className="h-8 text-xs font-semibold"
                  >
                    Confirm picked up
                  </Button>
                )}
                <PickupRowActions manifest={manifest} context={rowContext} />
              </div>
            );
          },
        };
      }),
    [rowContext, selectedIds, toggleOne, toggleMany, capabilities.canOperate, busyId]
  );

  const selectedWithLabels = useMemo(
    () =>
      visibleManifests.filter(
        (m) => selectedIds.has(m.id) && !m.is_blind_pickup && (m.expected_awbs ?? 0) > 0
      ),
    [visibleManifests, selectedIds]
  );

  const handleBulkPrint = async () => {
    for (const manifest of selectedWithLabels) {
      try {
        await downloadPickupLabels(manifest, PickupLabelFormat.A4);
      } catch {
        toast.error(`Failed to download labels for ${getPickupDisplayId(manifest)}.`);
      }
    }
  };

  const handleConfirm = async () => {
    if (!pendingConfirm) return;
    const { kind, manifest } = pendingConfirm;
    const pickupId = getPickupDisplayId(manifest);
    setDialogSubmitting(true);
    try {
      await _runConfirmedAction(kind, manifest.id, tenantSlug);
      toast.success(CONFIRM_COPY[kind].success(pickupId));
      setPendingConfirm(null);
      refresh();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Action failed. Please try again."));
    } finally {
      setDialogSubmitting(false);
    }
  };

  const handleNotPicked = async (reason: string) => {
    if (!notPickedTarget) return;
    const pickupId = getPickupDisplayId(notPickedTarget);
    setDialogSubmitting(true);
    try {
      await ManifestsService.markManifestNotPicked(
        notPickedTarget.id,
        { failure_reason: reason },
        tenantSlug
      );
      toast.success(`Pickup ${pickupId} marked as Not Picked.`);
      setNotPickedTarget(null);
      refresh();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to mark the pickup as not picked."));
    } finally {
      setDialogSubmitting(false);
    }
  };

  const hasFilters =
    searchTerm.trim() !== "" ||
    statusFilter !== ALL_VALUE ||
    locationFilter !== ALL_VALUE ||
    Boolean(dateRange?.from);

  const clearFilters = () => {
    setSearchTerm("");
    setStatusFilter(ALL_VALUE);
    setLocationFilter(ALL_VALUE);
    setDateRange(undefined);
  };

  const confirmCopy = pendingConfirm ? CONFIRM_COPY[pendingConfirm.kind] : null;

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Truck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground">
              {PICKUP_PAGE_TITLE}
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">{PICKUP_PAGE_SUBTITLE}</p>
          </div>
        </div>
        {capabilities.canBook && (
          <Button asChild className="h-10 rounded-lg px-4 font-semibold shadow-sm w-full sm:w-auto">
            <Link href={routeTo(flowConfig.createHref)}>
              Create pickup request <Plus className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        )}
      </div>

      {/* Filters: Search Pickup ID · Pickup date range · Pickup location · Status */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search Pickup ID"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            className="h-10 bg-card pl-9 shadow-sm"
          />
        </div>

        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              className={cn(
                "h-10 w-full justify-between bg-card font-normal shadow-sm sm:w-56",
                !dateRange?.from && "text-muted-foreground"
              )}
            >
              <span className="flex items-center gap-2">
                <CalendarRange className="h-4 w-4" />
                {_rangeLabel(dateRange)}
              </span>
              <ChevronDown className="h-4 w-4 opacity-60" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar mode="range" selected={dateRange} onSelect={setDateRange} numberOfMonths={1} />
            {dateRange?.from && (
              <div className="border-t border-border p-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full text-xs"
                  onClick={() => setDateRange(undefined)}
                >
                  Clear dates
                </Button>
              </div>
            )}
          </PopoverContent>
        </Popover>

        <Select value={locationFilter} onValueChange={setLocationFilter}>
          <SelectTrigger className="h-10 w-full bg-card shadow-sm sm:w-56">
            <SelectValue placeholder="Pickup location" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All pickup locations</SelectItem>
            {locationNames.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <IconSelect
          aria-label="Status"
          options={MANIFEST_STATUS_FILTER_OPTIONS}
          value={statusFilter}
          onValueChange={setStatusFilter}
          placeholder="Status"
          triggerClassName="h-10 w-full bg-card shadow-sm sm:w-52"
        />

        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters} className="text-muted-foreground">
            <X className="mr-1 h-3.5 w-3.5" /> Clear filters
          </Button>
        )}
      </div>

      {/* Bulk selection bar */}
      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 px-4 py-2.5 text-sm">
          <span className="font-semibold text-foreground">{selectedIds.size} selected</span>
          <Button
            size="sm"
            variant="outline"
            disabled={selectedWithLabels.length === 0}
            onClick={handleBulkPrint}
            className="h-8 text-xs font-semibold"
          >
            <Printer className="mr-1.5 h-3.5 w-3.5" /> Print labels
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setSelectedIds(new Set())}
            className="h-8 text-xs"
          >
            Clear selection
          </Button>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-sm font-medium text-destructive">
          {error}
        </div>
      )}

      {/* Desktop table */}
      <div className="relative hidden min-h-[320px] md:block">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-background/50 backdrop-blur-[1px]">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}
        <DataTable columns={columns} data={visibleManifests} />
      </div>

      {/* Mobile cards */}
      <div className="space-y-3 md:hidden">
        {loading && (
          <div className="flex justify-center py-10">
            <Loader2 className="h-7 w-7 animate-spin text-primary" />
          </div>
        )}
        {!loading && visibleManifests.length === 0 && (
          <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            No pickup requests found.
          </div>
        )}
        {!loading &&
          visibleManifests.map((manifest) => (
            <div
              key={manifest.id}
              className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label="Select pickup request"
                    className="h-4 w-4 rounded border-input accent-primary"
                    checked={selectedIds.has(manifest.id)}
                    onChange={() => toggleOne(manifest.id)}
                  />
                  <PickupIdLink manifest={manifest} />
                </div>
                <PickupDateSlot manifest={manifest} />
              </div>
              <PickupLocationCell manifest={manifest} />
              <PickupStatusCell manifest={manifest} flow={serviceFlow} />
              <PickupRowActions manifest={manifest} context={rowContext} />
            </div>
          ))}
      </div>

      {confirmCopy && pendingConfirm && (
        <ConfirmPickupDialog
          open
          title={confirmCopy.title(getPickupDisplayId(pendingConfirm.manifest))}
          description={confirmCopy.description}
          confirmLabel={confirmCopy.confirmLabel}
          destructive={confirmCopy.destructive}
          submitting={dialogSubmitting}
          onConfirm={handleConfirm}
          onOpenChange={(open) => {
            if (!open) setPendingConfirm(null);
          }}
        />
      )}

      <NotPickedDialog
        key={`not-picked-${notPickedTarget?.id ?? "none"}`}
        open={notPickedTarget !== null}
        pickupLabel={notPickedTarget ? getPickupDisplayId(notPickedTarget) : ""}
        submitting={dialogSubmitting}
        onSubmit={handleNotPicked}
        onOpenChange={(open) => {
          if (!open) setNotPickedTarget(null);
        }}
      />

      <DispatchPickupDialog
        key={`dispatch-${dispatchTarget?.id ?? "none"}`}
        open={dispatchTarget !== null}
        pickupLabel={dispatchTarget ? getPickupDisplayId(dispatchTarget) : ""}
        shipments={dispatchTarget?.shipments ?? []}
        submitting={dialogSubmitting}
        onSubmit={async (pickedIds, measurements) => {
          if (!dispatchTarget) return;
          const pickupId = getPickupDisplayId(dispatchTarget);
          setDialogSubmitting(true);
          try {
            await ManifestsService.dispatchManifest(
              dispatchTarget.id,
              tenantSlug,
              pickedIds.length > 0
                ? {
                    picked_shipment_ids: pickedIds,
                    measurements: measurements.length > 0 ? measurements : undefined,
                  }
                : undefined
            );
            if (measurements.length > 0) window.dispatchEvent(new CustomEvent("wallet-updated"));
            toast.success(`Pickup ${pickupId} marked as picked.`);
            setDispatchTarget(null);
            refresh();
          } catch (err: unknown) {
            toast.error(extractApiErrorMessage(err, "Failed to confirm pickup."));
          } finally {
            setDialogSubmitting(false);
          }
        }}
        onOpenChange={(open) => {
          if (!open) setDispatchTarget(null);
        }}
      />
    </div>
  );
}
