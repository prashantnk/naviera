// frontend/src/components/exceptions/exceptions-workspace.tsx
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  CalendarCheck,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  HelpCircle,
  Info,
  Loader2,
  MoreHorizontal,
  Package,
  RefreshCw,
  Search,
  ShieldAlert,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  ExceptionCategory,
  ExceptionPaymentMode,
  ExceptionsService,
  NdrAction,
  ServiceFlow,
  ShipmentType,
} from "@/api_client";
import type {
  ExceptionCategoryCount,
  ExceptionListResponse,
  ExceptionSummaryResponse,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { IconSelect, OptionIconTile } from "@/components/ui/icon-select";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  NDR_REASON_OPTIONS,
  getOptionMeta,
} from "@/lib/form-options";
import { cn, extractApiErrorMessage, safeFormatDate } from "@/lib/utils";
import {
  ExceptionActionDialog,
  type ExtendedExceptionRow,
} from "./exception-action-dialogs";
import {
  B2B_CATEGORY_ORDER,
  B2C_CATEGORY_ORDER,
  BULK_CAPABLE_ACTIONS,
  BULK_ENDPOINT_ACTIONS,
  CATEGORY_ORDER_BY_FLOW,
  EXCEPTIONS_PAGE_SIZE,
  EXCEPTION_CATEGORY_META,
  MAX_BULK_SELECTION,
  NDR_ACTION_META,
  SEARCH_DEBOUNCE_MS,
  categoryOptions,
  type ExceptionViewerRights,
  formatInr,
  visibleExceptionActions,
} from "./exception-meta";

const B2B_MOBILE_CATEGORY_OPTIONS = categoryOptions(B2B_CATEGORY_ORDER);

/**
 * Narrows a row's actions to what the viewer may click (see `visibleExceptionActions`).
 *
 * @param row - Exception row from the API.
 * @param rights - The viewer's rights.
 * @returns A copy of the row with the filtered `allowed_actions`.
 */
function _withVisibleActions(
  row: ExtendedExceptionRow,
  rights: ExceptionViewerRights,
): ExtendedExceptionRow {
  return Object.assign({}, row, {
    allowed_actions: visibleExceptionActions(row.allowed_actions, rights),
  });
}

const CHECKBOX_CLASS =
  "h-4 w-4 rounded border-slate-300 bg-white accent-primary cursor-pointer disabled:cursor-not-allowed disabled:opacity-40";

export interface ExceptionsWorkspaceProps {
  serviceFlow: ServiceFlow;
}

/** Query parameter that selects the active category (written by the side menu too). */
const CATEGORY_QUERY_PARAM = "category";

function _resolveInitialCategory(
  serviceFlow: ServiceFlow,
  paramValue: string | null,
): ExceptionCategory {
  const order = CATEGORY_ORDER_BY_FLOW[serviceFlow];
  if (paramValue && (order as readonly string[]).includes(paramValue)) {
    return paramValue as ExceptionCategory;
  }
  return order[0];
}

function _agingLabel(days: number): string {
  if (days <= 0) return "Today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export function ExceptionsWorkspace({ serviceFlow }: ExceptionsWorkspaceProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { tenantSlug, routeTo } = useTenant();
  const { capabilities } = useUser();
  const viewerRights: ExceptionViewerRights = useMemo(
    () => ({
      canWrite: capabilities.canWrite,
      canAcceptCharges: !capabilities.isStaff || capabilities.canManageFinance,
    }),
    [capabilities.canWrite, capabilities.isStaff, capabilities.canManageFinance],
  );
  const categoryParam = searchParams.get(CATEGORY_QUERY_PARAM);

  const isB2B = serviceFlow === ServiceFlow.B2B;
  const categoryOrder = CATEGORY_ORDER_BY_FLOW[serviceFlow];

  const [activeCategory, setActiveCategory] = useState<ExceptionCategory>(() =>
    _resolveInitialCategory(serviceFlow, categoryParam),
  );
  const [actionableOnly, setActionableOnly] = useState<boolean>(false);
  const [searchInput, setSearchInput] = useState<string>(
    () => searchParams.get("search") || "",
  );
  const [debouncedSearch, setDebouncedSearch] = useState<string>(
    () => searchParams.get("search") || "",
  );
  const [page, setPage] = useState<number>(1);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  const [summary, setSummary] = useState<ExceptionSummaryResponse | null>(null);
  const [listData, setListData] = useState<ExceptionListResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState<boolean>(false);

  // Dialog state for single or bulk action
  const [dialogAction, setDialogAction] = useState<NdrAction | null>(null);
  const [dialogRow, setDialogRow] = useState<ExtendedExceptionRow | null>(null);
  const [dialogBulkIds, setDialogBulkIds] = useState<string[]>([]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(searchInput.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const refresh = useCallback(() => {
    setRefreshKey((prev) => prev + 1);
  }, []);

  useEffect(() => {
    let ignore = false;
    setLoading(true);

    const effectiveActionable =
      activeCategory === ExceptionCategory.NON_ACTIONABLE ? false : actionableOnly;

    Promise.all([
      ExceptionsService.getExceptionsSummary(serviceFlow, tenantSlug),
      ExceptionsService.listExceptions(
        serviceFlow,
        activeCategory,
        effectiveActionable,
        debouncedSearch || null,
        page,
        EXCEPTIONS_PAGE_SIZE,
        tenantSlug,
      ),
    ])
      .then(([summaryRes, listRes]) => {
        if (ignore) return;
        setSummary(summaryRes);
        setListData(listRes);
        setError(null);
      })
      .catch((err: unknown) => {
        if (ignore) return;
        setError(
          extractApiErrorMessage(err, "Failed to load delivery exceptions."),
        );
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [
    serviceFlow,
    activeCategory,
    actionableOnly,
    debouncedSearch,
    page,
    tenantSlug,
    refreshKey,
  ]);

  // The URL `?category=` is the source of truth (sidebar sub-menu links set it).
  // Only reacts to URL changes; local tab clicks update the URL themselves.
  useEffect(() => {
    const fromUrl = _resolveInitialCategory(serviceFlow, categoryParam);
    if (fromUrl === activeCategory) return;
    setActiveCategory(fromUrl);
    setPage(1);
    setSelectedIds(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceFlow, categoryParam]);

  const handleCategoryChange = (nextCategory: ExceptionCategory) => {
    setActiveCategory(nextCategory);
    setPage(1);
    setSelectedIds(new Set());
    const params = new URLSearchParams(searchParams.toString());
    params.set(CATEGORY_QUERY_PARAM, nextCategory);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  const categoryCountsMap = useMemo(() => {
    const map = new Map<ExceptionCategory, ExceptionCategoryCount>();
    for (const item of summary?.categories || []) {
      map.set(item.category, item);
    }
    return map;
  }, [summary]);

  const rows: ExtendedExceptionRow[] = useMemo(
    () =>
      ((listData?.items as ExtendedExceptionRow[]) || []).map((row) =>
        _withVisibleActions(row, viewerRights),
      ),
    [listData, viewerRights],
  );

  const actionableRowsOnPage = useMemo(
    () => rows.filter((r) => r.is_actionable),
    [rows],
  );

  const allPageSelected =
    actionableRowsOnPage.length > 0 &&
    actionableRowsOnPage.every((r) => selectedIds.has(r.shipment_id));

  const toggleRowSelection = (shipmentId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(shipmentId)) {
        next.delete(shipmentId);
      } else {
        if (next.size >= MAX_BULK_SELECTION) {
          toast.error(`You can select up to ${MAX_BULK_SELECTION} shipments at once.`);
          return prev;
        }
        next.add(shipmentId);
      }
      return next;
    });
  };

  const toggleAllOnPage = (checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const r of actionableRowsOnPage) {
        if (checked) {
          if (next.size < MAX_BULK_SELECTION) {
            next.add(r.shipment_id);
          }
        } else {
          next.delete(r.shipment_id);
        }
      }
      return next;
    });
  };

  const selectedRows = useMemo(
    () => rows.filter((r) => selectedIds.has(r.shipment_id)),
    [rows, selectedIds],
  );

  const availableBulkActions = useMemo(() => {
    if (selectedRows.length === 0) return [];
    return BULK_CAPABLE_ACTIONS.filter((candidate) =>
      selectedRows.some((r) => (r.allowed_actions || []).includes(candidate)),
    );
  }, [selectedRows]);

  const openSingleActionDialog = (
    row: ExtendedExceptionRow,
    action: NdrAction,
  ) => {
    setDialogBulkIds([]);
    setDialogRow(row);
    setDialogAction(action);
  };

  const handleBulkActionClick = async (action: NdrAction) => {
    const eligibleIds = selectedRows
      .filter((r) => (r.allowed_actions || []).includes(action))
      .map((r) => r.shipment_id);

    if (eligibleIds.length === 0) {
      toast.error("None of the selected shipments allow this action.");
      return;
    }

    if (action === NdrAction.BOOK_APPOINTMENT) {
      setDialogRow(null);
      setDialogBulkIds(eligibleIds);
      setDialogAction(NdrAction.BOOK_APPOINTMENT);
      return;
    }

    if (!BULK_ENDPOINT_ACTIONS.has(action)) return;

    setBulkBusy(true);
    try {
      const res = await ExceptionsService.applyBulkExceptionAction(
        {
          action,
          shipment_ids: eligibleIds,
        },
        tenantSlug,
      );
      if (action === NdrAction.CANCEL_PICKUP) {
        window.dispatchEvent(new CustomEvent("wallet-updated"));
      }
      const okCount = res.succeeded.length;
      const failCount = res.failed.length;
      const label = NDR_ACTION_META[action].label;
      if (okCount > 0) {
        toast.success(`${label} applied to ${okCount} shipment(s).`);
      }
      if (failCount > 0) {
        toast.error(
          `${failCount} shipment(s) could not be processed: ${res.failed[0]?.reason || "Validation error"}`,
        );
      }
      setSelectedIds(new Set());
      refresh();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Bulk action failed."));
    } finally {
      setBulkBusy(false);
    }
  };

  const handleBulkAppointmentHeaderButton = () => {
    const eligibleFromSelection = selectedRows
      .filter((r) =>
        (r.allowed_actions || []).includes(NdrAction.BOOK_APPOINTMENT),
      )
      .map((r) => r.shipment_id);

    if (eligibleFromSelection.length > 0) {
      setDialogRow(null);
      setDialogBulkIds(eligibleFromSelection);
      setDialogAction(NdrAction.BOOK_APPOINTMENT);
      return;
    }

    const eligibleOnPage = actionableRowsOnPage
      .filter((r) =>
        (r.allowed_actions || []).includes(NdrAction.BOOK_APPOINTMENT),
      )
      .map((r) => r.shipment_id);

    if (eligibleOnPage.length === 0) {
      toast.info("No shipments needing an appointment on this page.");
      return;
    }

    setSelectedIds(new Set(eligibleOnPage));
    setDialogRow(null);
    setDialogBulkIds(eligibleOnPage);
    setDialogAction(NdrAction.BOOK_APPOINTMENT);
  };

  const activeCategoryMeta = EXCEPTION_CATEGORY_META[activeCategory];
  const summaryHoldCount = summary ? summary.total : 0;
  const summaryActionableCount = summary ? summary.actionable : 0;
  const listRowCount = listData ? listData.total : 0;
  const pageCount = Math.max(1, listData?.pages || 1);

  const shipmentBasePath = isB2B ? "/b2b/shipments" : "/shipments";

  const renderRowActions = (row: ExtendedExceptionRow) => {
    const allowed = row.allowed_actions || [];
    if (!row.is_actionable || allowed.length === 0) {
      return (
        <span className="text-xs font-medium text-slate-400">
          {row.awaiting_ops ? "With operations" : "View only"}
        </span>
      );
    }

    const primaryAction = allowed[0];
    const primaryMeta = NDR_ACTION_META[primaryAction];
    const PrimaryIcon = primaryMeta.icon;
    const secondaryActions = allowed.slice(1);

    return (
      <div
        className="flex items-center justify-end gap-1.5"
        onClick={(event) => event.stopPropagation()}
      >
        <Button
          size="sm"
          variant="outline"
          className="h-8 border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-800 hover:bg-slate-50 shadow-2xs"
          onClick={() => openSingleActionDialog(row, primaryAction)}
        >
          <PrimaryIcon className="mr-1.5 size-3.5 text-primary" />
          {primaryMeta.label}
        </Button>

        {secondaryActions.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                aria-label="More exception actions"
                className="h-8 w-8 border-slate-200 bg-white p-0 text-slate-600 hover:bg-slate-50"
              >
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {secondaryActions.map((act) => {
                const actMeta = NDR_ACTION_META[act];
                return (
                  <DropdownMenuItem
                    key={act}
                    className="cursor-pointer gap-2.5 py-2 text-xs font-medium"
                    onClick={() => openSingleActionDialog(row, act)}
                  >
                    <OptionIconTile option={actMeta} size="sm" />
                    <div className="flex flex-col">
                      <span className="font-semibold text-slate-900">
                        {actMeta.label}
                      </span>
                      <span className="text-[11px] text-slate-500">
                        {actMeta.description}
                      </span>
                    </div>
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    );
  };

  const renderStatusBadge = (row: ExtendedExceptionRow) => {
    if (row.is_actionable) {
      return (
        <Badge
          variant="outline"
          className="border-amber-200 bg-amber-50 text-amber-800 text-[11px] font-semibold"
        >
          Action required
        </Badge>
      );
    }
    if (row.awaiting_ops) {
      return (
        <Badge
          variant="outline"
          className="border-sky-200 bg-sky-50 text-sky-800 text-[11px] font-semibold"
        >
          Awaiting operations
        </Badge>
      );
    }
    return (
      <Badge
        variant="outline"
        className="border-slate-200 bg-slate-100 text-slate-600 text-[11px] font-semibold"
      >
        Handled by ops
      </Badge>
    );
  };

  const renderIssueCell = (row: ExtendedExceptionRow) => {
    const reasonMeta = getOptionMeta(NDR_REASON_OPTIONS, row.ndr_reason);
    const reasonLabel =
      reasonMeta?.label || row.ndr_reason?.replace(/_/g, " ") || "Exception";
    const chargeAmt = row.charge_amount_payable ?? row.charge_amount;
    const measuredKg = row.measured_weight_kg;
    const isCodPayment = row.payment_mode === ExceptionPaymentMode.COD;
    const collectableAmt = row.cod_amount;

    return (
      <div className="space-y-1 max-w-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          {reasonMeta && <OptionIconTile option={reasonMeta} size="sm" />}
          <span className="text-xs font-bold text-slate-900">{reasonLabel}</span>
          {chargeAmt != null && chargeAmt > 0 && (
            <Badge
              variant="outline"
              className="border-amber-300 bg-amber-50 font-mono text-[11px] font-bold text-amber-900"
            >
              {formatInr(chargeAmt)}
            </Badge>
          )}
          {measuredKg != null && measuredKg > 0 && (
            <Badge
              variant="outline"
              className="border-amber-300 bg-amber-50 font-mono text-[11px] font-bold text-amber-900"
            >
              {`${measuredKg} kg`}
            </Badge>
          )}
        </div>
        {row.last_remark && (
          <p className="text-xs text-slate-600 italic line-clamp-2">
            &ldquo;{row.last_remark}&rdquo;
          </p>
        )}
        <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <span className="font-semibold">
            {isCodPayment
              ? `COD ${formatInr(collectableAmt)}`
              : "Prepaid"}
          </span>
        </div>
      </div>
    );
  };

  const renderMainContent = () => (
    <div className="flex-1 min-w-0 space-y-5">
      {/* Category Header + Learn More Popover */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <OptionIconTile option={activeCategoryMeta} size="md" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight text-slate-900">
                {isB2B ? activeCategoryMeta.label : "Delivery Exceptions & NDR"}
              </h1>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs font-semibold text-primary hover:bg-primary/10"
                  >
                    <HelpCircle className="mr-1 size-3.5" />
                    Learn more
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-80 text-xs space-y-2">
                  <div className="flex items-center gap-2 font-bold text-slate-900">
                    <OptionIconTile option={activeCategoryMeta} size="sm" />
                    <span>{activeCategoryMeta.label}</span>
                  </div>
                  <p className="text-slate-600 leading-relaxed">
                    {activeCategoryMeta.help}
                  </p>
                </PopoverContent>
              </Popover>
            </div>
            <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
              {isB2B
                ? activeCategoryMeta.description
                : "Resolve held parcels, undelivered attempts (NDR) and reverse pickup failures (NPR)"}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className="border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700"
          >
            On hold: {summaryHoldCount}
          </Badge>
          <Badge
            variant="outline"
            className="border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800"
          >
            Actionable: {summaryActionableCount}
          </Badge>
          {isB2B &&
            activeCategory === ExceptionCategory.APPOINTMENT_NEEDED && (
              <Button
                variant="outline"
                size="sm"
                className="h-9 text-xs font-semibold"
                onClick={handleBulkAppointmentHeaderButton}
              >
                <CalendarCheck className="mr-1.5 size-3.5 text-primary" />
                Bulk Appointment Booking
              </Button>
            )}
        </div>
      </div>

      {/* B2C Top Category Tabs */}
      {!isB2B && (
        <div
          role="tablist"
          aria-label="B2C exception groups"
          className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4"
        >
          {B2C_CATEGORY_ORDER.map((category) => {
            const meta = EXCEPTION_CATEGORY_META[category];
            const counts = categoryCountsMap.get(category);
            const badgeNumber = actionableOnly
              ? (counts?.actionable ?? 0)
              : (counts?.total ?? 0);
            const isSelected = activeCategory === category;

            return (
              <button
                key={category}
                role="tab"
                type="button"
                aria-selected={isSelected}
                onClick={() => handleCategoryChange(category)}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-xl border p-3 text-left transition-all cursor-pointer",
                  isSelected
                    ? "border-primary bg-primary/5 shadow-2xs"
                    : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/60",
                )}
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <OptionIconTile option={meta} size="md" />
                  <div className="min-w-0">
                    <div className="truncate text-xs font-bold text-slate-900">
                      {meta.label}
                    </div>
                    <div className="truncate text-[11px] text-slate-500">
                      {meta.description}
                    </div>
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full px-2 font-mono text-xs font-bold",
                    isSelected
                      ? "bg-primary text-primary-foreground"
                      : "bg-slate-100 text-slate-700",
                  )}
                >
                  {badgeNumber}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* B2B Mobile Category Picker */}
      {isB2B && (
        <div className="lg:hidden">
          <IconSelect
            aria-label="Exception category"
            options={B2B_MOBILE_CATEGORY_OPTIONS}
            value={activeCategory}
            onValueChange={handleCategoryChange}
            triggerClassName="h-10 bg-white"
          />
        </div>
      )}

      {/* Appointment 6:00 PM Cutoff Callout */}
      {activeCategory === ExceptionCategory.APPOINTMENT_NEEDED && (
        <div className="flex items-center gap-2.5 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs font-medium text-amber-900">
          <Info className="size-4 shrink-0 text-amber-600" />
          <span>
            Appointments for tomorrow must be booked before 6:00 PM today.
          </span>
        </div>
      )}

      {/* Search + Actionable-Only Switch + Refresh */}
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative min-w-0 w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={
              isB2B
                ? "Search by LRN / AWB or Order ID"
                : "Search by AWB or Order ID"
            }
            className="min-w-0 w-full h-9 bg-white pl-9 pr-8 text-xs shadow-2xs"
          />
          {searchInput && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setSearchInput("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {activeCategory !== ExceptionCategory.NON_ACTIONABLE && (
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs select-none">
              <input
                type="checkbox"
                className={CHECKBOX_CLASS}
                checked={actionableOnly}
                onChange={(event) => {
                  setActionableOnly(event.target.checked);
                  setPage(1);
                }}
              />
              <span>Actionable only</span>
            </label>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={loading}
            className="h-9 bg-white text-xs font-semibold"
          >
            <RefreshCw
              className={cn("mr-1.5 size-3.5", loading && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Multi-select Bulk Action Bar */}
      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/25 bg-primary/5 px-4 py-2.5 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-900">
              {selectedIds.size} selected
            </span>
            <span className="text-slate-500">
              (max {MAX_BULK_SELECTION} per batch)
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {availableBulkActions.map((bulkAction) => {
              const bulkMeta = NDR_ACTION_META[bulkAction];
              const BulkIcon = bulkMeta.icon;
              return (
                <Button
                  key={bulkAction}
                  size="sm"
                  variant="outline"
                  disabled={bulkBusy}
                  onClick={() => handleBulkActionClick(bulkAction)}
                  className="h-8 bg-white text-xs font-semibold shadow-2xs"
                >
                  {bulkBusy ? (
                    <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                  ) : (
                    <BulkIcon className="mr-1.5 size-3.5 text-primary" />
                  )}
                  {bulkMeta.label}
                </Button>
              );
            })}

            <Button
              size="sm"
              variant="ghost"
              disabled={bulkBusy}
              onClick={() => setSelectedIds(new Set())}
              className="h-8 text-xs text-slate-600"
            >
              Clear selection
            </Button>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-semibold text-rose-800">
          {error}
        </div>
      )}

      {/* Desktop Table */}
      <div className="relative hidden md:block rounded-xl border border-slate-200 bg-white shadow-2xs overflow-hidden">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60 backdrop-blur-[1px]">
            <Loader2 className="size-7 animate-spin text-primary" />
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/80 text-[11px] font-bold uppercase tracking-wider text-slate-600">
                <th className="w-10 px-4 py-3">
                  <input
                    type="checkbox"
                    aria-label="Select all actionable shipments on this page"
                    className={CHECKBOX_CLASS}
                    checked={allPageSelected}
                    disabled={actionableRowsOnPage.length === 0}
                    onChange={(event) => toggleAllOnPage(event.target.checked)}
                  />
                </th>
                <th className="px-4 py-3">
                  {isB2B ? "LRN & Boxes" : "Shipment"}
                </th>
                <th className="px-4 py-3">Consignee & Route</th>
                <th className="px-4 py-3">Issue & Remark</th>
                <th className="px-4 py-3">Attempts</th>
                <th className="px-4 py-3">Aging</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.length === 0 && !loading ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center">
                    <div className="mx-auto flex max-w-sm flex-col items-center gap-2 text-slate-500">
                      <CheckCircle2 className="size-8 text-emerald-500" />
                      <p className="text-sm font-bold text-slate-900">
                        No exceptions in {activeCategoryMeta.label}
                      </p>
                      <p className="text-xs text-slate-500">
                        All shipments in this bucket are moving smoothly or match no
                        active filter.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const postalPin = row.consignee.pincode;
                  const isReverse = row.shipment_type === ShipmentType.REVERSE;
                  const detailHref = routeTo(
                    `${shipmentBasePath}/${row.shipment_id}`,
                  );

                  return (
                    <tr
                      key={row.shipment_id}
                      onClick={() => router.push(detailHref)}
                      className="cursor-pointer transition-colors hover:bg-slate-50/80"
                    >
                      <td
                        className="px-4 py-3.5 align-top"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          aria-label={`Select shipment ${row.tracking_id || row.shipment_id}`}
                          className={CHECKBOX_CLASS}
                          checked={
                            row.is_actionable && selectedIds.has(row.shipment_id)
                          }
                          disabled={!row.is_actionable}
                          onChange={() => toggleRowSelection(row.shipment_id)}
                        />
                      </td>

                      {/* Shipment */}
                      <td className="px-4 py-3.5 align-top">
                        <div className="space-y-1">
                          <Link
                            href={detailHref}
                            onClick={(event) => event.stopPropagation()}
                            className="font-mono text-xs font-bold text-primary hover:underline"
                          >
                            {row.tracking_id || "Pending AWB"}
                          </Link>
                          <div className="text-[11px] text-slate-500">
                            Order: {row.order_reference_id || "—"}
                          </div>
                          <div className="flex flex-wrap items-center gap-1 pt-0.5">
                            <Badge
                              variant="outline"
                              className={cn(
                                "px-1.5 py-0 text-[10px] font-bold",
                                isReverse
                                  ? "border-amber-200 bg-amber-50 text-amber-800"
                                  : "border-sky-200 bg-sky-50 text-sky-800",
                              )}
                            >
                              {isReverse ? "Reverse" : "Forward"}
                            </Badge>
                            {isB2B && (
                              <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-700">
                                <Package className="size-3" />
                                {row.box_count}
                              </span>
                            )}
                          </div>
                          {isB2B && row.pdd && (
                            <div className="text-[11px] text-slate-500">
                              PDD: {safeFormatDate(row.pdd, "dd MMM yyyy")}
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Consignee & Route */}
                      <td className="px-4 py-3.5 align-top">
                        <div className="space-y-0.5">
                          <div className="font-semibold text-slate-900">
                            {row.consignee.name}
                          </div>
                          <div className="font-mono text-[11px] text-slate-500">
                            {row.consignee.phone}
                          </div>
                          <div className="text-[11px] text-slate-600">
                            {row.consignee.city} ({postalPin})
                          </div>
                          <div className="text-[10px] font-medium text-slate-400">
                            {row.origin_city} → {row.destination_city}
                          </div>
                        </div>
                      </td>

                      {/* Issue */}
                      <td className="px-4 py-3.5 align-top">
                        {renderIssueCell(row)}
                      </td>

                      {/* Attempts */}
                      <td className="px-4 py-3.5 align-top">
                        <Badge
                          variant="outline"
                          className={cn(
                            "font-mono text-xs font-bold",
                            row.attempts >= row.max_attempts
                              ? "border-rose-200 bg-rose-50 text-rose-800"
                              : "border-slate-200 bg-slate-50 text-slate-700",
                          )}
                        >
                          {`${row.attempts} of ${row.max_attempts}`}
                        </Badge>
                      </td>

                      {/* Aging */}
                      <td className="px-4 py-3.5 align-top">
                        <span className="inline-flex items-center gap-1 font-medium text-slate-700">
                          <Clock className="size-3 text-slate-400" />
                          {_agingLabel(row.aging_days)}
                        </span>
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3.5 align-top">
                        {renderStatusBadge(row)}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3.5 align-top text-right">
                        {renderRowActions(row)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50/60 px-4 py-3 text-xs text-slate-600">
          <span>
            Page {page} of {pageCount} · {listRowCount} shipment(s)
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="h-8 bg-white text-xs"
            >
              <ChevronLeft className="mr-1 size-3.5" />
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= pageCount || loading}
              onClick={() => setPage((p) => p + 1)}
              className="h-8 bg-white text-xs"
            >
              Next
              <ChevronRight className="ml-1 size-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {/* Mobile Cards */}
      <div className="space-y-3 md:hidden">
        {loading && (
          <div className="flex justify-center py-10">
            <Loader2 className="size-7 animate-spin text-primary" />
          </div>
        )}

        {!loading && rows.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
            No exceptions in {activeCategoryMeta.label}.
          </div>
        )}

        {!loading &&
          rows.map((row) => {
            const postalPin = row.consignee.pincode;
            const detailHref = routeTo(`${shipmentBasePath}/${row.shipment_id}`);
            return (
              <div
                key={row.shipment_id}
                className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-2xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      aria-label={`Select shipment ${row.tracking_id || row.shipment_id}`}
                      className={CHECKBOX_CLASS}
                      checked={
                        row.is_actionable && selectedIds.has(row.shipment_id)
                      }
                      disabled={!row.is_actionable}
                      onChange={() => toggleRowSelection(row.shipment_id)}
                    />
                    <div>
                      <Link
                        href={detailHref}
                        className="font-mono text-xs font-bold text-primary hover:underline"
                      >
                        {row.tracking_id || "Pending AWB"}
                      </Link>
                      <div className="text-[11px] text-slate-500">
                        Order: {row.order_reference_id || "—"}
                      </div>
                    </div>
                  </div>
                  {renderStatusBadge(row)}
                </div>

                <div className="text-xs text-slate-700">
                  <span className="font-semibold">{row.consignee.name}</span> ·{" "}
                  {row.consignee.city} ({postalPin}) · {row.consignee.phone}
                </div>

                {renderIssueCell(row)}

                <div className="flex items-center justify-between border-t border-slate-100 pt-2.5 text-[11px] text-slate-500">
                  <span>
                    Attempts: {row.attempts} of {row.max_attempts} · Aging:{" "}
                    {_agingLabel(row.aging_days)}
                  </span>
                  {renderRowActions(row)}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto pb-12 animate-in fade-in duration-300">
      {isB2B ? (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          {/* Desktop Left Category Rail (11 Delhivery Cargo categories) */}
          <aside
            aria-label="B2B exception categories"
            className="hidden lg:flex lg:w-72 shrink-0 flex-col rounded-xl border border-slate-200 bg-white shadow-2xs overflow-hidden"
          >
            <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/80 px-4 py-3">
              <div className="flex items-center gap-2">
                <ShieldAlert className="size-4 text-primary" />
                <span className="text-xs font-bold uppercase tracking-wider text-slate-800">
                  Exceptions & NDR
                </span>
              </div>
              <Badge
                variant="secondary"
                className="bg-primary/10 text-primary font-mono text-xs font-bold"
              >
                {summaryHoldCount}
              </Badge>
            </div>

            <nav className="divide-y divide-slate-100 p-1.5">
              {categoryOrder.map((category) => {
                const meta = EXCEPTION_CATEGORY_META[category];
                const counts = categoryCountsMap.get(category);
                const countValue = actionableOnly
                  ? (counts?.actionable ?? 0)
                  : (counts?.total ?? 0);
                const isSelected = activeCategory === category;

                return (
                  <button
                    key={category}
                    type="button"
                    onClick={() => handleCategoryChange(category)}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-left text-xs transition-colors cursor-pointer",
                      isSelected
                        ? "bg-primary/10 font-bold text-primary"
                        : "font-medium text-slate-700 hover:bg-slate-50",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <OptionIconTile option={meta} size="sm" />
                      <span className="truncate">{meta.label}</span>
                    </span>
                    <span
                      className={cn(
                        "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1.5 font-mono text-[11px] font-bold",
                        countValue > 0
                          ? isSelected
                            ? "bg-primary text-primary-foreground"
                            : "bg-amber-100 text-amber-900"
                          : "bg-slate-100 text-slate-500",
                      )}
                    >
                      {countValue}
                    </span>
                  </button>
                );
              })}
            </nav>
          </aside>

          {renderMainContent()}
        </div>
      ) : (
        renderMainContent()
      )}

      <ExceptionActionDialog
        open={dialogAction !== null}
        action={dialogAction}
        row={dialogRow}
        bulkShipmentIds={dialogBulkIds}
        tenantSlug={tenantSlug}
        onOpenChange={(open) => {
          if (!open) {
            setDialogAction(null);
            setDialogRow(null);
            setDialogBulkIds([]);
          }
        }}
        onSuccess={() => {
          setSelectedIds(new Set());
          refresh();
        }}
      />
    </div>
  );
}
