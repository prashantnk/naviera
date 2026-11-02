// frontend/src/components/pickups/orders-workspace.tsx
"use client";

/**
 * Delhivery One "Orders" page, shared by B2C `/shipments` and B2B `/b2b/shipments`.
 *
 * Layout (matches the Delhivery reference screenshot):
 * - Header: title, `Download CSV`, `+ Create shipment ▾` (Forward / Reverse), kebab.
 * - Left status rail with counts (Ready to ship … All shipments).
 * - Compact filter row: AWB/Order ID search · Manifested date · Transport mode · All filters.
 * - "Ready to ship" banner with `Add all orders to pickup`.
 * - Grid (desktop) / card list (mobile).
 *
 * Data fetching, `?status=` deep links, row selection + `AddToPickupBar` are
 * unchanged from the previous pages. All numbers come from the API.
 */
import {
  PickupStatus,
  ServiceType,
  ShipmentType,
  ShipmentsService,
  type PickupRead,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { AddToPickupBar } from "@/components/pickups/add-to-pickup-bar";
import {
  buildOrderColumnsWithSelection,
  formatManifestedDate,
  OrderIdCell,
  OrderRowActions,
  OrderStatusText,
  ORDERS_FLOW_COPY,
  PaymentModeCell,
  PickupDeliveryCell,
  TransportCell,
} from "@/components/pickups/order-columns";
import { PICKUP_FLOW_CONFIG } from "@/components/pickups/pickup-constants";
import {
  isShipmentPickupSelectable,
  SHIPMENT_STATUS_FILTER_OPTIONS,
} from "@/components/pickups/status-display";
import { useShipmentStatusQuery } from "@/components/pickups/use-shipment-status-query";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { IconSelect } from "@/components/ui/icon-select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { downloadShipmentsCsv } from "@/lib/api";
import { cn, parseUtcDate } from "@/lib/utils";
import { B2B_REVERSE_BOOKING_ENABLED } from "@/lib/mvp-scope";
import { directionTabsFor } from "./order-direction";
import { ServiceFlow } from "@/lib/workspace-flow";
import { differenceInCalendarDays } from "date-fns";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Calculator,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Download,
  Loader2,
  MoreVertical,
  Plus,
  Search,
  SlidersHorizontal,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

/** Rows fetched per page (unchanged from the previous pages). */
const PAGE_SIZE = 50;

/** Value used by every "no filter" option. */
const ALL = "ALL";

/** Delhivery One left status rail bucket definition. */
interface StatusRailBucket {
  id: string;
  label: string;
  queryValue: string;
  statuses: readonly PickupStatus[];
}

const READY_TO_SHIP_BUCKET_ID = "READY_TO_SHIP";
const ALL_BUCKET_ID = "ALL";

export const ORDER_STATUS_BUCKETS: readonly StatusRailBucket[] = [
  {
    id: READY_TO_SHIP_BUCKET_ID,
    label: "Ready to ship",
    queryValue: `${PickupStatus.OPEN},${PickupStatus.DRAFT}`,
    statuses: [PickupStatus.OPEN, PickupStatus.DRAFT],
  },
  {
    id: "READY_FOR_PICKUP",
    label: "Ready for pickup",
    queryValue: PickupStatus.ASSIGNED,
    statuses: [PickupStatus.ASSIGNED],
  },
  {
    id: "IN_TRANSIT",
    label: "In transit",
    queryValue: `${PickupStatus.IN_TRANSIT},${PickupStatus.EXCEPTION}`,
    statuses: [PickupStatus.IN_TRANSIT, PickupStatus.EXCEPTION],
  },
  {
    id: "OUT_FOR_DELIVERY",
    label: "Out for delivery",
    queryValue: PickupStatus.OUT_FOR_DELIVERY,
    statuses: [PickupStatus.OUT_FOR_DELIVERY],
  },
  {
    id: "RTO_IN_TRANSIT",
    label: "RTO - In transit",
    queryValue: `${PickupStatus.RTO_INITIATED},${PickupStatus.RTO_IN_TRANSIT}`,
    statuses: [PickupStatus.RTO_INITIATED, PickupStatus.RTO_IN_TRANSIT],
  },
  {
    id: "RTO_DELIVERED",
    label: "RTO - Delivered",
    queryValue: PickupStatus.RTO_DELIVERED,
    statuses: [PickupStatus.RTO_DELIVERED],
  },
  {
    id: "DELIVERED",
    label: "Delivered",
    queryValue: PickupStatus.COMPLETED,
    statuses: [PickupStatus.COMPLETED],
  },
  { id: ALL_BUCKET_ID, label: "All shipments", queryValue: ALL, statuses: [] },
];

/** Manifested date presets (days back, inclusive of today). */
enum ManifestedRange {
  ALL = "ALL",
  TODAY = "TODAY",
  LAST_7 = "LAST_7",
  LAST_30 = "LAST_30",
}

const MANIFESTED_RANGE_DAYS: Readonly<Record<ManifestedRange, number | null>> = {
  [ManifestedRange.ALL]: null,
  [ManifestedRange.TODAY]: 0,
  [ManifestedRange.LAST_7]: 6,
  [ManifestedRange.LAST_30]: 29,
};

const MANIFESTED_RANGE_LABELS: Readonly<Record<ManifestedRange, string>> = {
  [ManifestedRange.ALL]: "Manifested date",
  [ManifestedRange.TODAY]: "Today",
  [ManifestedRange.LAST_7]: "Last 7 days",
  [ManifestedRange.LAST_30]: "Last 30 days",
};

/** Delhivery transport mode filter. */
enum TransportFilter {
  ALL = "ALL",
  EXPRESS = "EXPRESS",
  SURFACE = "SURFACE",
}

const TRANSPORT_FILTER_LABELS: Readonly<Record<TransportFilter, string>> = {
  [TransportFilter.ALL]: "Transport mode",
  [TransportFilter.EXPRESS]: "Express",
  [TransportFilter.SURFACE]: "Surface",
};

/** Payment filter inside "All filters". */
enum PaymentFilter {
  ALL = "ALL",
  PREPAID = "PREPAID",
  COD = "COD",
}

/** Per-flow page copy. */
interface OrdersPageCopy {
  title: string;
  createForwardLabel: string;
  createForwardHref: string;
  createReverseLabel: string;
  /** Null when reverse booking is off for the flow (B2B in the MVP, WP0). */
  createReverseHref: string | null;
  searchPlaceholder: string;
  csvSuccess: string;
  rowNoun: string;
  rateCalculatorHref: string;
}

const PAGE_COPY: Readonly<Record<ServiceFlow, OrdersPageCopy>> = {
  [ServiceFlow.B2C]: {
    title: "Orders",
    createForwardLabel: "Forward",
    createForwardHref: "/shipments/new/forward",
    createReverseLabel: "Reverse",
    createReverseHref: "/shipments/new/reverse",
    searchPlaceholder: "Search AWB or Order ID",
    csvSuccess: "Orders CSV exported.",
    rowNoun: "shipment",
    rateCalculatorHref: "/rate-calculator",
  },
  [ServiceFlow.B2B]: {
    title: "B2B Orders",
    createForwardLabel: "Forward LR",
    createForwardHref: "/b2b/shipments/new/forward",
    createReverseLabel: "Reverse",
    createReverseHref: B2B_REVERSE_BOOKING_ENABLED ? "/b2b/shipments/new/reverse" : null,
    searchPlaceholder: "Search LRN or Order ID",
    csvSuccess: "B2B orders CSV exported.",
    rowNoun: "LR",
    rateCalculatorHref: "/b2b/rate-calculator",
  },
};

/**
 * Maps the URL status filter to the rail bucket it represents.
 *
 * @param statuses - Statuses from `?status=` (empty = all).
 * @returns Matching bucket id, or "ALL" for custom combinations.
 */
export function resolveActiveBucketId(statuses: ReadonlySet<PickupStatus>): string {
  if (statuses.size === 0) return ALL_BUCKET_ID;
  const selected = Array.from(statuses);
  const match = ORDER_STATUS_BUCKETS.find(
    (bucket) =>
      bucket.statuses.length > 0 && selected.every((status) => bucket.statuses.includes(status))
  );
  return match ? match.id : ALL_BUCKET_ID;
}

/**
 * Whether a row was manifested inside the chosen preset.
 *
 * @param createdAt - Row `created_at`.
 * @param range - Selected preset.
 * @param today - Reference day (injectable for tests).
 * @returns True when the row passes the filter.
 */
export function isWithinManifestedRange(
  createdAt: string | null | undefined,
  range: ManifestedRange,
  today: Date = new Date()
): boolean {
  const daysBack = MANIFESTED_RANGE_DAYS[range];
  if (daysBack === null) return true;
  if (!createdAt) return false;
  const created = parseUtcDate(createdAt);
  if (!created) return false;
  const age = differenceInCalendarDays(today, created);
  return age >= 0 && age <= daysBack;
}

/**
 * Whether a row matches the Delhivery transport filter.
 *
 * @param shipment - Row data.
 * @param filter - Selected transport filter.
 * @returns True when the row passes.
 */
function _matchesTransport(shipment: PickupRead, filter: TransportFilter): boolean {
  if (filter === TransportFilter.ALL) return true;
  const isExpress = shipment.service_type === ServiceType.AIR;
  return filter === TransportFilter.EXPRESS ? isExpress : !isExpress;
}

/**
 * Whether a row matches the AWB / order id search (comma or space separated, up to 100).
 *
 * @param shipment - Row data.
 * @param terms - Lower-cased search terms.
 * @returns True when any term matches the AWB, order id, PO or invoice numbers.
 */
function _matchesSearch(shipment: PickupRead, terms: readonly string[]): boolean {
  if (terms.length === 0) return true;
  const haystack = [
    shipment.tracking_id || "",
    shipment.order_reference_id || "",
    shipment.po_number || "",
    (shipment.payment_details?.invoice_numbers || []).join(" "),
  ]
    .join(" ")
    .toLowerCase();
  return terms.some((term) => haystack.includes(term));
}

/** Max AWBs accepted by the search box (Delhivery: "Search upto 100 AWBs"). */
const MAX_SEARCH_TERMS = 100;

/**
 * Splits the search box into lower-cased terms.
 *
 * @param raw - Raw input.
 * @returns Up to 100 non-empty terms.
 */
export function parseSearchTerms(raw: string): string[] {
  return raw
    .toLowerCase()
    .split(/[\s,]+/)
    .filter(Boolean)
    .slice(0, MAX_SEARCH_TERMS);
}

interface OrdersWorkspaceProps {
  flow: ServiceFlow;
}

export function OrdersWorkspace({ flow }: OrdersWorkspaceProps) {
  const router = useRouter();
  const { routeTo } = useTenant();
  const { capabilities } = useUser();
  const copy = PAGE_COPY[flow];
  const gridCopy = ORDERS_FLOW_COPY[flow];
  const isB2B = flow === ServiceFlow.B2B;
  const directionTabs = directionTabsFor(flow);
  const canBook = capabilities.canBook;

  const [data, setData] = useState<PickupRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [itemCount, setItemCount] = useState(0);

  const [searchQuery, setSearchQuery] = useState("");
  const [manifestedRange, setManifestedRange] = useState<ManifestedRange>(ManifestedRange.ALL);
  const [transportFilter, setTransportFilter] = useState<TransportFilter>(TransportFilter.ALL);
  const [directionFilter, setDirectionFilter] = useState<string>(ALL);
  const [paymentFilter, setPaymentFilter] = useState<PaymentFilter>(PaymentFilter.ALL);
  const { statusFilter, statuses, isMultiStatus, setStatusFilter } = useShipmentStatusQuery();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoOpenPickupDialog, setAutoOpenPickupDialog] = useState(false);
  const pickupBarRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let ignore = false;
    const fetchShipments = async () => {
      setLoading(true);
      try {
        const shipmentTypeParam =
          directionFilter === ALL ? undefined : (directionFilter as ShipmentType);
        const response = await ShipmentsService.listShipments(
          pageIndex + 1,
          PAGE_SIZE,
          isB2B,
          undefined,
          shipmentTypeParam
        );
        if (ignore) return;
        setData(response.items);
        setItemCount(response.total);
        setError(null);
      } catch (err: unknown) {
        if (ignore) return;
        const errorObj = err as { message?: string };
        setError(errorObj.message || "Failed to fetch orders.");
      } finally {
        if (!ignore) setLoading(false);
      }
    };
    fetchShipments();
    return () => {
      ignore = true;
    };
  }, [pageIndex, refreshKey, isB2B, directionFilter]);

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleManySelected = useCallback((ids: string[], checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  // Only Ready to Ship rows of the current page count as selected.
  const pageSelectedIds = useMemo(
    () =>
      new Set(
        data
          .filter((row) => selectedIds.has(row.id) && isShipmentPickupSelectable(row.status))
          .map((row) => row.id)
      ),
    [data, selectedIds]
  );

  const columns = useMemo(
    () =>
      buildOrderColumnsWithSelection(
        flow,
        { canBook },
        canBook
          ? {
              selectedIds: pageSelectedIds,
              onToggle: toggleSelected,
              onToggleMany: toggleManySelected,
              isSelectable: (row) => isShipmentPickupSelectable(row.status),
              rowNoun: copy.rowNoun,
            }
          : null
      ),
    [flow, canBook, pageSelectedIds, toggleSelected, toggleManySelected, copy.rowNoun]
  );

  const bucketCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const bucket of ORDER_STATUS_BUCKETS) {
      counts[bucket.id] =
        bucket.statuses.length === 0
          ? data.length
          : data.filter((item) => bucket.statuses.includes(item.status)).length;
    }
    return counts;
  }, [data]);

  const activeBucketId = useMemo(() => resolveActiveBucketId(statuses), [statuses]);
  const searchTerms = useMemo(() => parseSearchTerms(searchQuery), [searchQuery]);

  const filteredData = useMemo(
    () =>
      data.filter((shipment) => {
        if (statuses.size > 0 && !statuses.has(shipment.status)) return false;
        if (!_matchesTransport(shipment, transportFilter)) return false;
        if (!isWithinManifestedRange(shipment.created_at, manifestedRange)) return false;
        if (directionFilter !== ALL && shipment.shipment_type !== directionFilter) return false;
        if (paymentFilter !== PaymentFilter.ALL) {
          const isCod = Boolean(shipment.payment_details?.is_cod);
          if ((paymentFilter === PaymentFilter.COD) !== isCod) return false;
        }
        return _matchesSearch(shipment, searchTerms);
      }),
    [data, statuses, transportFilter, manifestedRange, directionFilter, paymentFilter, searchTerms]
  );

  const visibleOpenIds = useMemo(
    () => filteredData.filter((row) => row.status === PickupStatus.OPEN).map((row) => row.id),
    [filteredData]
  );

  useEffect(() => {
    if (!autoOpenPickupDialog || pageSelectedIds.size === 0) return;
    setAutoOpenPickupDialog(false);
    pickupBarRef.current?.querySelector("button")?.click();
  }, [autoOpenPickupDialog, pageSelectedIds]);

  const handleAddAllOrdersToPickup = useCallback(() => {
    if (visibleOpenIds.length === 0) return;
    setSelectedIds(new Set(visibleOpenIds));
    setAutoOpenPickupDialog(true);
  }, [visibleOpenIds]);

  const handleDownloadCsv = async () => {
    try {
      await downloadShipmentsCsv(isB2B);
      toast.success(copy.csvSuccess);
    } catch {
      toast.error("Failed to export orders CSV.");
    }
  };

  const activeExtraFilters =
    (directionFilter !== ALL ? 1 : 0) +
    (paymentFilter !== PaymentFilter.ALL ? 1 : 0) +
    (statusFilter !== ALL && activeBucketId === ALL_BUCKET_ID ? 1 : 0);

  const pageCount = Math.max(1, Math.ceil(itemCount / PAGE_SIZE));
  const canNextPage = pageIndex < pageCount - 1;
  const canPreviousPage = pageIndex > 0;
  const handleNextPage = () => canNextPage && setPageIndex((prev) => prev + 1);
  const handlePreviousPage = () => canPreviousPage && setPageIndex((prev) => prev - 1);
  const detailHref = (row: PickupRead) => routeTo(`${gridCopy.basePath}/${row.id}`);
  const showReadyBanner =
    canBook && activeBucketId === READY_TO_SHIP_BUCKET_ID && visibleOpenIds.length > 0;

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 pb-12 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
            <ClipboardList className="h-5 w-5 text-primary" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">{copy.title}</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={handleDownloadCsv}
            className="h-10 border-slate-300 px-3 font-semibold"
          >
            <Download className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Download CSV</span>
          </Button>
          {canBook && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button className="h-10 px-3 font-semibold">
                  <Plus className="mr-1.5 h-4 w-4" />
                  Create shipment
                  <ChevronDown className="ml-1.5 h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem asChild>
                  <Link href={routeTo(copy.createForwardHref)}>
                    <ArrowUpRight className="mr-2 h-4 w-4 text-slate-500" />
                    {copy.createForwardLabel}
                  </Link>
                </DropdownMenuItem>
                {copy.createReverseHref && (
                  <DropdownMenuItem asChild>
                    <Link href={routeTo(copy.createReverseHref)}>
                      <ArrowDownLeft className="mr-2 h-4 w-4 text-slate-500" />
                      {copy.createReverseLabel}
                    </Link>
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                aria-label="More options"
                className="h-10 w-10 border-slate-300"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem asChild>
                <Link href={routeTo(PICKUP_FLOW_CONFIG[flow].listHref)}>
                  <Truck className="mr-2 h-4 w-4 text-slate-500" />
                  Pickup Requests
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href={routeTo(copy.rateCalculatorHref)}>
                  <Calculator className="mr-2 h-4 w-4 text-slate-500" />
                  Rate calculator
                </Link>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="lg:grid lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-5">
        {/* Left status rail (desktop) / scrollable pills (mobile) */}
        <aside
          aria-label="Order status"
          className="-mx-1 mb-3 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:mx-0 lg:mb-0 lg:flex-col lg:gap-1 lg:overflow-visible lg:border-r lg:border-slate-200 lg:px-0 lg:pr-4"
        >
          {ORDER_STATUS_BUCKETS.map((bucket) => {
            const isActive = activeBucketId === bucket.id;
            return (
              <button
                key={bucket.id}
                type="button"
                onClick={() => setStatusFilter(bucket.queryValue)}
                aria-pressed={isActive}
                className={cn(
                  "flex shrink-0 items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors lg:w-full",
                  isActive
                    ? "bg-primary/10 font-semibold text-slate-900"
                    : "text-slate-700 hover:bg-slate-100"
                )}
              >
                <span className="whitespace-nowrap">{bucket.label}</span>
                <span
                  className={cn(
                    "inline-flex min-w-[24px] items-center justify-center rounded-full px-1.5 py-0.5 text-[11px] font-bold",
                    isActive ? "bg-primary text-primary-foreground" : "bg-slate-100 text-slate-600"
                  )}
                >
                  {bucketCounts[bucket.id] ?? 0}
                </span>
              </button>
            );
          })}
        </aside>

        <div className="min-w-0 space-y-3">
          {/* Top Direction Sub-Tabs: All Orders / Forward Orders / Reverse (B2C: DTO returns).
              Hidden on B2B while reverse LRs are off for the MVP (WP0). */}
          {directionTabs.length > 0 && (
          <div
            role="tablist"
            aria-label="Order direction filter"
            className="inline-flex flex-wrap items-center gap-1 rounded-xl border border-slate-200 bg-slate-100/80 p-1"
          >
            {directionTabs.map((tab) => {
              const isSelected = directionFilter === tab.value;
              const Icon = tab.icon;
              return (
                <button
                  key={tab.value}
                  type="button"
                  role="tab"
                  aria-selected={isSelected}
                  onClick={() => {
                    setDirectionFilter(tab.value);
                    setPageIndex(0);
                  }}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition-all",
                    isSelected
                      ? "bg-primary text-primary-foreground shadow-xs"
                      : "text-slate-600 hover:text-slate-900"
                  )}
                >
                  {Icon && <Icon className="h-3.5 w-3.5" />}
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>
          )}

          {/* Compact filter row */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full sm:w-72">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                placeholder={copy.searchPlaceholder}
                aria-label={copy.searchPlaceholder}
                className="h-10 border-slate-300 bg-white pl-9"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
            <Select
              value={manifestedRange}
              onValueChange={(value) => setManifestedRange(value as ManifestedRange)}
            >
              <SelectTrigger
                aria-label="Manifested date"
                className="h-10 w-[calc(50%-4px)] border-slate-300 bg-white sm:w-[170px]"
              >
                <SelectValue placeholder="Manifested date" />
              </SelectTrigger>
              <SelectContent>
                {Object.values(ManifestedRange).map((range) => (
                  <SelectItem key={range} value={range}>
                    {range === ManifestedRange.ALL ? "Any date" : MANIFESTED_RANGE_LABELS[range]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={transportFilter}
              onValueChange={(value) => setTransportFilter(value as TransportFilter)}
            >
              <SelectTrigger
                aria-label="Transport mode"
                className="h-10 w-[calc(50%-4px)] border-slate-300 bg-white sm:w-[160px]"
              >
                <SelectValue placeholder="Transport mode" />
              </SelectTrigger>
              <SelectContent>
                {Object.values(TransportFilter).map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {mode === TransportFilter.ALL ? "Any mode" : TRANSPORT_FILTER_LABELS[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" className="h-10 border-slate-300 bg-white font-normal">
                  <SlidersHorizontal className="mr-2 h-4 w-4 text-slate-500" />
                  All filters
                  {activeExtraFilters > 0 && (
                    <span className="ml-2 rounded-full bg-primary px-1.5 text-[11px] font-bold text-primary-foreground">
                      {activeExtraFilters}
                    </span>
                  )}
                  <ChevronRight className="ml-1 h-4 w-4 text-slate-400" />
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-72 space-y-3">
                {directionTabs.length > 0 && (
                <div className="space-y-1.5">
                  <Label className="text-xs font-semibold">Shipment type</Label>
                  <Select value={directionFilter} onValueChange={setDirectionFilter}>
                    <SelectTrigger className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL}>All types</SelectItem>
                      <SelectItem value={ShipmentType.FORWARD}>Forward</SelectItem>
                      <SelectItem value={ShipmentType.REVERSE}>Reverse</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                )}
                <div className="space-y-1.5">
                  <Label className="text-xs font-semibold">Payment mode</Label>
                  <Select
                    value={paymentFilter}
                    onValueChange={(value) => setPaymentFilter(value as PaymentFilter)}
                  >
                    <SelectTrigger className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={PaymentFilter.ALL}>All</SelectItem>
                      <SelectItem value={PaymentFilter.PREPAID}>Prepaid</SelectItem>
                      <SelectItem value={PaymentFilter.COD}>COD</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-semibold">Exact status</Label>
                  <IconSelect
                    aria-label="Exact status"
                    options={SHIPMENT_STATUS_FILTER_OPTIONS}
                    value={statusFilter}
                    onValueChange={setStatusFilter}
                    placeholder={isMultiStatus ? `${statuses.size} statuses` : "Exact status"}
                    triggerClassName="h-9 w-full"
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full"
                  onClick={() => {
                    setDirectionFilter(ALL);
                    setPaymentFilter(PaymentFilter.ALL);
                    setStatusFilter(ALL);
                  }}
                >
                  Clear filters
                </Button>
              </PopoverContent>
            </Popover>
          </div>

          {/* Ready to ship banner */}
          {showReadyBanner && (
            <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2.5">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-slate-800" />
                <span>Schedule pickup before the cut-off to get a pickup on the next slot.</span>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={handleAddAllOrdersToPickup}
                className="h-8 shrink-0 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-800"
              >
                Add all orders to pickup
              </Button>
            </div>
          )}

          {canBook && (
            <div ref={pickupBarRef}>
              <AddToPickupBar
                selectedIds={Array.from(pageSelectedIds)}
                onClear={() => setSelectedIds(new Set())}
                onAdded={() => setRefreshKey((key) => key + 1)}
              />
            </div>
          )}

          {/* Desktop grid */}
          <div className="relative hidden min-h-[360px] md:block">
            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-white/60">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            )}
            <DataTable
              columns={columns}
              data={filteredData}
              onRowClick={(row) => router.push(detailHref(row))}
              pageCount={pageCount}
              pageIndex={pageIndex}
              onNextPage={handleNextPage}
              onPreviousPage={handlePreviousPage}
              canNextPage={canNextPage}
              canPreviousPage={canPreviousPage}
            />
          </div>

          {/* Mobile card list */}
          <div className="space-y-3 md:hidden">
            {loading && (
              <div className="flex justify-center py-10">
                <Loader2 className="h-7 w-7 animate-spin text-primary" />
              </div>
            )}
            {!loading && filteredData.length === 0 && (
              <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
                No orders found. Try another status or filter.
              </div>
            )}
            {!loading &&
              filteredData.map((shipment) => {
                const manifested = formatManifestedDate(shipment.created_at);
                const selectable = canBook && isShipmentPickupSelectable(shipment.status);
                return (
                  <div
                    key={shipment.id}
                    className="space-y-3 rounded-xl border border-slate-200 bg-white p-3 shadow-2xs"
                  >
                    <div className="flex items-start gap-2">
                      {selectable && (
                        <input
                          type="checkbox"
                          aria-label={`Select ${copy.rowNoun}`}
                          className="mt-1 h-4 w-4 accent-primary"
                          checked={pageSelectedIds.has(shipment.id)}
                          onChange={() => toggleSelected(shipment.id)}
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <OrderIdCell shipment={shipment} copy={gridCopy} />
                      </div>
                      <OrderStatusText status={shipment.status} />
                    </div>
                    <PickupDeliveryCell shipment={shipment} />
                    <div className="grid grid-cols-3 gap-2 border-t border-slate-100 pt-2 text-xs">
                      <div>
                        <p className="text-slate-500">Manifested</p>
                        <p className="font-medium text-slate-800">{manifested?.date ?? "-"}</p>
                      </div>
                      <TransportCell shipment={shipment} />
                      <PaymentModeCell shipment={shipment} flow={flow} />
                    </div>
                    <OrderRowActions
                      shipment={shipment}
                      copy={gridCopy}
                      permissions={{ canBook }}
                      compact
                    />
                  </div>
                );
              })}
            {pageCount > 1 && (
              <div className="flex items-center justify-between pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePreviousPage}
                  disabled={!canPreviousPage}
                >
                  <ChevronLeft className="mr-1 h-4 w-4" /> Previous
                </Button>
                <span className="text-xs text-slate-500">
                  Page {pageIndex + 1} of {pageCount}
                </span>
                <Button variant="outline" size="sm" onClick={handleNextPage} disabled={!canNextPage}>
                  Next <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
