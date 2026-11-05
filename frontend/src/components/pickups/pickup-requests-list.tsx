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
import {
  ManifestResponse,
  ManifestsService,
  ManifestStatus,
  ServiceFlow,
  UserRole,
} from "@/api_client";
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
import { prefetchAddresses } from "@/hooks/use-addresses";
import { useProgressRouter } from "@/hooks/use-progress-router";
import { useSingleFlight } from "@/hooks/use-single-flight";
import {
  buildQueryCacheKey,
  fetchWithCache,
  getCachedQuery,
  hasCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import { format } from "date-fns";
import { CalendarRange, ChevronDown, Loader2, Plus, Printer, Search, Truck, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { DateRange } from "react-day-picker";
import { toast } from "sonner";

import { buildEligibleShipmentsCacheKey } from "./create-pickup-request-form";
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

/** Extended manifest shape supporting optional city, pincode, transporter & vehicle search fields. */
export type SearchableManifest = ManifestResponse & {
  pickup_city?: string | null;
  pickup_pincode?: string | null;
  transporter_name?: string | null;
  vehicle_number?: string | null;
};

/**
 * Whether a Pickup Request matches the generic omni-search query.
 *
 * Matches against the display Pickup ID, UUID, pickup request number, warehouse location name,
 * formatted address, city, pincode, status, time slot, transporter, vehicle number, and
 * any linked shipment AWB/LRN or Order ID.
 *
 * @param manifest - Pickup Request row.
 * @param rawQuery - Raw search input.
 * @returns True when the query is empty or matches the manifest haystack.
 */
export function matchesManifestSearch(manifest: SearchableManifest, rawQuery: string): boolean {
  const query = rawQuery.trim().toLowerCase();
  if (!query) return true;
  const shipmentTokens = (manifest.shipments ?? []).flatMap((item) => [
    item.tracking_id,
    item.order_reference_id,
  ]);
  const haystack = [
    getPickupDisplayId(manifest),
    manifest.id,
    manifest.pickup_request_number,
    manifest.pickup_location_name,
    manifest.pickup_location_address,
    manifest.pickup_city,
    manifest.pickup_pincode,
    manifest.status,
    manifest.time_slot,
    manifest.transporter_name,
    manifest.vehicle_number,
    ...shipmentTokens,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (haystack.includes(query)) return true;
  const terms = query.split(/[\s,]+/).filter(Boolean);
  return terms.length > 0 && terms.every((term) => haystack.includes(term));
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
  const router = useProgressRouter();
  const { tenantSlug, routeTo } = useTenant();
  const { user, capabilities } = useUser();
  const flowConfig = PICKUP_FLOW_CONFIG[serviceFlow];
  const canOverrideOtp =
    user?.role === UserRole.OWNER || user?.role === UserRole.ADMIN;

  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>(ALL_VALUE);
  const [locationFilter, setLocationFilter] = useState<string>(ALL_VALUE);
  const [dateRange, setDateRange] = useState<DateRange | undefined>(undefined);

  const [refreshKey, setRefreshKey] = useState(0);
  const requestKey = `${serviceFlow}|${statusFilter}|${tenantSlug}|${refreshKey}`;
  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "manifests-list", {
    serviceFlow,
    status: statusFilter,
  });

  const [manifests, setManifests] = useState<ManifestResponse[]>(
    () => getCachedQuery<ManifestResponse[]>(cacheKey) ?? []
  );
  const [loadedRequestKey, setLoadedRequestKey] = useState<string | null>(() =>
    hasCachedQuery(cacheKey) ? requestKey : null
  );
  const [error, setError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const { pending: rowBusy, pendingKey: busyId, run: runRowAction } = useSingleFlight();
  const { pending: dialogSubmitting, run: runDialogAction } = useSingleFlight();
  const { pending: bulkPrinting, run: runBulkPrint } = useSingleFlight();
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  const [notPickedTarget, setNotPickedTarget] = useState<ManifestResponse | null>(null);
  const [dispatchTarget, setDispatchTarget] = useState<ManifestResponse | null>(null);
  const [dispatchError, setDispatchError] = useState<string | null>(null);

  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  // Loading is derived: the list is loading until the current request key has completed
  // (or when a fresh cache entry already exists for the current filter).
  const loading = loadedRequestKey !== requestKey && !hasCachedQuery(cacheKey);

  useEffect(() => {
    let ignore = false;
    const cached = getCachedQuery<ManifestResponse[]>(cacheKey);
    if (cached !== null) {
      setManifests(cached);
    }
    const status = statusFilter === ALL_VALUE ? null : (statusFilter as ManifestStatus);
    ManifestsService.listManifests(serviceFlow, status, null, tenantSlug)
      .then((rows) => {
        setCachedQuery(cacheKey, rows);
        if (ignore) return;
        setManifests(rows);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!ignore && cached === null) {
          setError(extractApiErrorMessage(err, "Failed to load pickup requests."));
        }
      })
      .finally(() => {
        if (!ignore) setLoadedRequestKey(requestKey);
      });
    return () => {
      ignore = true;
    };
  }, [serviceFlow, statusFilter, tenantSlug, requestKey, cacheKey]);

  // Pre-warm saved pickup locations and Ready to Ship shipments in the background
  // so clicking "Create pickup request" renders in 0ms with addresses + shipments populated.
  useEffect(() => {
    if (!tenantSlug || !capabilities.canBook) return;
    let cancelled = false;
    void prefetchAddresses(tenantSlug).then((addresses) => {
      if (cancelled || !addresses || addresses.length === 0) return;
      for (const addr of addresses.slice(0, 3)) {
        const eligibleKey = buildEligibleShipmentsCacheKey(tenantSlug, serviceFlow, addr.id);
        if (!hasCachedQuery(eligibleKey)) {
          void fetchWithCache(eligibleKey, () =>
            Promise.resolve(ManifestsService.listEligibleShipments(serviceFlow, addr.id, tenantSlug))
          ).catch(() => {});
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, serviceFlow, capabilities.canBook]);

  const locationNames = useMemo(() => {
    const names = new Set(manifests.map((m) => m.pickup_location_name).filter(Boolean));
    return Array.from(names) as string[];
  }, [manifests]);

  const visibleManifests = useMemo(() => {
    return manifests.filter((m) => {
      if (!matchesManifestSearch(m, searchTerm)) return false;
      if (locationFilter !== ALL_VALUE && m.pickup_location_name !== locationFilter) return false;
      return _isWithinRange(m.scheduled_date, dateRange);
    });
  }, [manifests, searchTerm, locationFilter, dateRange]);

  const handlers: PickupRowHandlers = useMemo(
    () => ({
      onPrintLabel: (manifest, labelFormat) => {
        void runRowAction(async () => {
          try {
            await downloadPickupLabels(manifest, labelFormat);
            toast.success(`Labels for pickup ${getPickupDisplayId(manifest)} downloaded.`);
          } catch (err: unknown) {
            toast.error(extractApiErrorMessage(err, "Failed to download labels."));
          }
        }, manifest.id);
      },
      onManifestCopy: (manifest) => {
        void runRowAction(async () => {
          try {
            await downloadPickupManifestCopy(manifest);
            toast.success(`Manifest copy for ${getPickupDisplayId(manifest)} downloaded.`);
          } catch (err: unknown) {
            toast.error(extractApiErrorMessage(err, "Failed to download the manifest copy."));
          }
        }, manifest.id);
      },
      onCancel: (manifest) => setPendingConfirm({ kind: ConfirmKind.CANCEL, manifest }),
      onOutForPickup: (manifest) => setPendingConfirm({ kind: ConfirmKind.OUT_FOR_PICKUP, manifest }),
      onMarkPicked: (manifest) => {
        setDispatchError(null);
        setDispatchTarget(manifest);
      },
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
    [router, routeTo, runRowAction, serviceFlow]
  );

  const rowContext: PickupRowContext = useMemo(
    () => ({
      flow: serviceFlow,
      canOperate: capabilities.canOperate,
      canBook: capabilities.canBook,
      handlers,
      busyId,
      rowBusy,
    }),
    [serviceFlow, capabilities.canOperate, capabilities.canBook, handlers, busyId, rowBusy]
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
                    disabled={rowBusy}
                    data-testid={`pickup-requests.row.${purId}.confirm-picked`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setDispatchError(null);
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
    [rowContext, selectedIds, toggleOne, toggleMany, capabilities.canOperate, rowBusy]
  );

  const selectedWithLabels = useMemo(
    () =>
      visibleManifests.filter(
        (m) => selectedIds.has(m.id) && !m.is_blind_pickup && (m.expected_awbs ?? 0) > 0
      ),
    [visibleManifests, selectedIds]
  );

  const handleBulkPrint = () => {
    void runBulkPrint(async () => {
      for (const manifest of selectedWithLabels) {
        try {
          await downloadPickupLabels(manifest, PickupLabelFormat.A4);
          toast.success(`Labels for pickup ${getPickupDisplayId(manifest)} downloaded.`);
        } catch (err: unknown) {
          toast.error(
            extractApiErrorMessage(err, `Failed to download labels for ${getPickupDisplayId(manifest)}.`)
          );
        }
      }
    });
  };

  const handleConfirm = async () => {
    if (!pendingConfirm) return;
    const { kind, manifest } = pendingConfirm;
    const pickupId = getPickupDisplayId(manifest);
    await runDialogAction(async () => {
      try {
        await _runConfirmedAction(kind, manifest.id, tenantSlug);
        toast.success(CONFIRM_COPY[kind].success(pickupId));
        setPendingConfirm(null);
        refresh();
      } catch (err: unknown) {
        toast.error(extractApiErrorMessage(err, "Action failed. Please try again."));
      }
    });
  };

  const handleNotPicked = async (reason: string) => {
    if (!notPickedTarget) return;
    const pickupId = getPickupDisplayId(notPickedTarget);
    await runDialogAction(async () => {
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
      }
    });
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
            <Link href={routeTo(flowConfig.createHref)} prefetch={true}>
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
            placeholder="Search Pickup ID, location, city, PIN..."
            aria-label="Search Pickup ID, location, city, PIN..."
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
            disabled={bulkPrinting || selectedWithLabels.length === 0}
            onClick={handleBulkPrint}
            className="h-8 text-xs font-semibold"
          >
            {bulkPrinting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Printer className="mr-1.5 h-3.5 w-3.5" />
            )}
            Print labels
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
        {loading && manifests.length === 0 ? (
          <div
            data-testid="pickup-requests-loading-skeleton"
            aria-busy="true"
            aria-label="Loading pickup requests"
            className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-3"
          >
            <div className="h-9 w-full animate-pulse rounded-lg bg-muted/60" />
            {[0, 1, 2, 3].map((rowIdx) => (
              <div
                key={rowIdx}
                className="grid grid-cols-5 gap-4 items-center py-3 border-b border-border/60 last:border-b-0"
              >
                <div className="h-4 w-28 animate-pulse rounded bg-muted/70" />
                <div className="h-4 w-44 animate-pulse rounded bg-muted/50" />
                <div className="h-4 w-32 animate-pulse rounded bg-muted/50" />
                <div className="h-6 w-24 animate-pulse rounded-full bg-muted/60" />
                <div className="h-8 w-28 animate-pulse rounded-lg bg-muted/50 justify-self-end" />
              </div>
            ))}
          </div>
        ) : (
          <DataTable columns={columns} data={visibleManifests} />
        )}
      </div>

      {/* Mobile cards */}
      <div className="space-y-3 md:hidden">
        {loading && manifests.length === 0 && (
          <div className="space-y-3">
            {[0, 1, 2].map((rowIdx) => (
              <div
                key={rowIdx}
                className="h-28 w-full animate-pulse rounded-xl border border-border bg-card p-4"
              />
            ))}
          </div>
        )}
        {(!loading || manifests.length > 0) && visibleManifests.length === 0 && (
          <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            No pickup requests found.
          </div>
        )}
        {(!loading || manifests.length > 0) &&
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
        canOverrideOtp={canOverrideOtp}
        errorMessage={dispatchError}
        onSubmit={async (pickedIds, measurements, pickupOtp, overrideReason) => {
          if (!dispatchTarget) return;
          const pickupId = getPickupDisplayId(dispatchTarget);
          setDispatchError(null);
          await runDialogAction(async () => {
            try {
              await ManifestsService.dispatchManifest(dispatchTarget.id, tenantSlug, {
                picked_shipment_ids: pickedIds.length > 0 ? pickedIds : undefined,
                measurements: measurements.length > 0 ? measurements : undefined,
                pickup_otp: pickupOtp || undefined,
                pickup_otp_override_reason: overrideReason || undefined,
              });
              if (measurements.length > 0) window.dispatchEvent(new CustomEvent("wallet-updated"));
              toast.success(`Pickup ${pickupId} marked as picked.`);
              setDispatchTarget(null);
              refresh();
            } catch (err: unknown) {
              const msg = extractApiErrorMessage(err, "Failed to confirm pickup.");
              setDispatchError(msg);
              toast.error(msg);
            }
          });
        }}
        onOpenChange={(open) => {
          if (!open) {
            setDispatchError(null);
            setDispatchTarget(null);
          }
        }}
      />
    </div>
  );
}
