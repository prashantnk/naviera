// frontend/src/app/[tenant_slug]/(app)/b2b/appointments/page.tsx
"use client";

/**
 * B2B "Manage Appointments" (Delhivery One parity, decision D24).
 *
 * Tabs Pending / At risk / Booked with live counts (same definitions as the B2B
 * dashboard), filters (LR search, consignee, city, shipment status, delivery
 * date range, expired POs), the LR table and the "Book appointment" modal.
 * Booking uses the existing `PATCH /shipments/{id}/appointment`.
 */
import {
  AppointmentsService,
  AppointmentTab,
  PickupStatus,
  type AppointmentListResponse,
  type AppointmentRow,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import {
  buildQueryCacheKey,
  getCachedQuery,
  hasCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import {
  CalendarClock,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  MoreVertical,
  Plus,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  APPOINTMENT_PAGE_SIZES,
  APPOINTMENT_STATUS_FILTERS,
  APPOINTMENT_TABS,
  DEFAULT_APPOINTMENT_PAGE_SIZE,
  formatAppointmentDate,
  PoState,
  resolvePoState,
} from "./_components/appointment-helpers";
import { BookAppointmentDialog } from "./_components/book-appointment-dialog";

/** Debounce for text filters (ms). */
const FILTER_DEBOUNCE_MS = 400;
const ALL = "ALL";

/** Debounces a string value. */
function useDebounced(value: string): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value.trim()), FILTER_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [value]);
  return debounced;
}

/** PO expiry cell: date, or red "PO missing" / "PO expired". */
function PoExpiryCell({ row }: { row: AppointmentRow }) {
  const state = resolvePoState(row);
  if (state === PoState.MISSING) {
    return <span className="text-sm font-medium text-destructive">PO missing</span>;
  }
  const formatted = formatAppointmentDate(row.po_expiry_date) ?? "-";
  if (state === PoState.EXPIRED) {
    return (
      <div className="flex flex-col">
        <span className="text-sm font-medium text-destructive">PO expired</span>
        <span className="text-xs text-slate-500">{formatted}</span>
      </div>
    );
  }
  return <span className="text-sm text-slate-800">{formatted}</span>;
}

/** Shipment status pill + "Delivery by". */
function StatusCell({ row }: { row: AppointmentRow }) {
  const deliveryBy = formatAppointmentDate(row.delivery_by, true);
  return (
    <div className="flex flex-col items-start gap-1">
      <span className="rounded bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
        {getShipmentStatusLabel(row.status)}
      </span>
      {deliveryBy && <span className="text-xs text-slate-600">Delivery by {deliveryBy}</span>}
    </div>
  );
}

/** LRN link + box count. */
function LrCell({ row }: { row: AppointmentRow }) {
  const { routeTo } = useTenant();
  return (
    <div className="flex flex-col">
      <Link
        href={routeTo(`/b2b/shipments/${row.shipment_id}`)}
        className="font-mono text-sm font-semibold text-primary hover:underline"
      >
        {row.tracking_id || row.order_reference_id || "Pending"}
      </Link>
      <span className="text-xs text-slate-500">
        {row.box_count} {row.box_count === 1 ? "Box" : "Boxes"}
      </span>
    </div>
  );
}

/** Consignee name/company + city, pincode. */
function ConsigneeCell({ row }: { row: AppointmentRow }) {
  const names = [row.consignee_name, row.consignee_company].filter(Boolean).join(", ");
  const place = [row.consignee_city, row.consignee_pincode].filter(Boolean).join(", ");
  return (
    <div className="flex min-w-0 flex-col">
      <span className="truncate text-sm font-medium text-slate-800">{names || "-"}</span>
      <span className="text-xs text-slate-500">{place}</span>
    </div>
  );
}

interface RowActionsProps {
  row: AppointmentRow;
  canBook: boolean;
  isBookedTab: boolean;
  onBook: (row: AppointmentRow) => void;
}

/** "Book appointment ›" (or "Reschedule ›") + kebab. */
function RowActions({ row, canBook, isBookedTab, onBook }: RowActionsProps) {
  const { routeTo } = useTenant();
  return (
    <div className="flex items-center justify-end gap-1">
      {canBook && (
        <Button
          type="button"
          variant="link"
          className="h-8 px-1 font-semibold text-primary"
          onClick={() => onBook(row)}
        >
          {isBookedTab ? "Reschedule" : "Book appointment"}
          <ChevronRight className="ml-0.5 h-4 w-4" />
        </Button>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="More actions" className="h-8 w-8">
            <MoreVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem asChild>
            <Link href={routeTo(`/b2b/shipments/${row.shipment_id}`)}>
              <Eye className="mr-2 h-4 w-4 text-slate-500" />
              View LR
            </Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default function ManageAppointmentsPage() {
  const { tenantSlug } = useTenant();
  const { capabilities } = useUser();
  // Booking only needs write access (backend `assert_not_read_only`).
  const canBook = capabilities.canWrite;

  const [tab, setTab] = useState<AppointmentTab>(AppointmentTab.PENDING);
  const [searchInput, setSearchInput] = useState("");
  const [consigneeInput, setConsigneeInput] = useState("");
  const [cityInput, setCityInput] = useState("");
  const [status, setStatus] = useState<string>(ALL);
  const [pddFrom, setPddFrom] = useState("");
  const [pddTo, setPddTo] = useState("");
  const [expiredOnly, setExpiredOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_APPOINTMENT_PAGE_SIZE);
  const [refreshKey, setRefreshKey] = useState(0);

  const search = useDebounced(searchInput);
  const consignee = useDebounced(consigneeInput);
  const city = useDebounced(cityInput);

  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "b2b-appointments", {
    tab,
    search,
    consignee,
    city,
    status,
    pddFrom,
    pddTo,
    expiredOnly,
    page,
    size,
  });

  const [data, setData] = useState<AppointmentListResponse | null>(() =>
    getCachedQuery<AppointmentListResponse>(cacheKey)
  );
  const [loading, setLoading] = useState<boolean>(
    () => !hasCachedQuery(cacheKey)
  );
  const [error, setError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [dialogRows, setDialogRows] = useState<AppointmentRow[]>([]);

  // Any filter change goes back to page 1 and clears the selection.
  useEffect(() => {
    setPage(1);
    setSelectedIds(new Set());
  }, [tab, search, consignee, city, status, pddFrom, pddTo, expiredOnly, size]);

  useEffect(() => {
    let ignore = false;
    const cached = getCachedQuery<AppointmentListResponse>(cacheKey);
    if (cached !== null && refreshKey === 0) {
      setData(cached);
      setLoading(false);
    } else if (cached === null) {
      setLoading(true);
    }
    AppointmentsService.listAppointments(
      tab,
      search || null,
      consignee || null,
      city || null,
      status === ALL ? null : (status as PickupStatus),
      pddFrom || null,
      pddTo || null,
      expiredOnly,
      page,
      size,
      tenantSlug
    )
      .then((response) => {
        setCachedQuery(cacheKey, response);
        if (ignore) return;
        setData(response);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!ignore && cached === null) {
          setError(extractApiErrorMessage(err, "Failed to load appointments."));
        }
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [tab, search, consignee, city, status, pddFrom, pddTo, expiredOnly, page, size, tenantSlug, refreshKey, cacheKey]);

  const rows = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / size));
  const firstRow = total === 0 ? 0 : (page - 1) * size + 1;
  const lastRow = Math.min(page * size, total);
  const selectedRows = rows.filter((row) => selectedIds.has(row.shipment_id));
  const allSelected = rows.length > 0 && rows.every((row) => selectedIds.has(row.shipment_id));
  const isBookedTab = tab !== AppointmentTab.PENDING;

  const toggleRow = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = () => {
    setSelectedIds(allSelected ? new Set() : new Set(rows.map((row) => row.shipment_id)));
  };

  const dateRangeLabel =
    pddFrom || pddTo
      ? `${formatAppointmentDate(pddFrom, true) ?? "…"} – ${formatAppointmentDate(pddTo, true) ?? "…"}`
      : "PDD date range";

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 pb-12 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
          <CalendarClock className="h-6 w-6 text-slate-700" />
          Manage Appointments
        </h1>
        {canBook && (
          <Button
            variant="outline"
            className="h-10 border-slate-300"
            disabled={selectedRows.length === 0}
            title={selectedRows.length === 0 ? "Select LRs in the table first" : undefined}
            onClick={() => setDialogRows(selectedRows)}
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Create bulk appointment
            {selectedRows.length > 0 && ` (${selectedRows.length})`}
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div role="tablist" className="flex gap-6 overflow-x-auto border-b border-slate-200">
        {APPOINTMENT_TABS.map(({ tab: value, label }) => {
          const isActive = tab === value;
          const count = data?.counts[value] ?? 0;
          return (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setTab(value)}
              className={cn(
                "-mb-px flex shrink-0 items-center gap-2 border-b-2 px-1 pb-2.5 pt-1 text-sm transition-colors",
                isActive
                  ? "border-primary font-semibold text-slate-900"
                  : "border-transparent text-slate-600 hover:text-slate-900"
              )}
            >
              {label}
              <span
                className={cn(
                  "inline-flex min-w-[20px] items-center justify-center rounded-full px-1.5 text-[11px] font-bold",
                  isActive ? "bg-primary text-primary-foreground" : "bg-slate-200 text-slate-700"
                )}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-56">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            aria-label="Search LR number"
            placeholder="Search LR number"
            className="h-10 border-slate-300 bg-white pl-9"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <Input
          aria-label="Consignee"
          placeholder="Consignee"
          className="h-10 w-[calc(50%-4px)] border-slate-300 bg-white sm:w-44"
          value={consigneeInput}
          onChange={(event) => setConsigneeInput(event.target.value)}
        />
        <Input
          aria-label="City"
          placeholder="City"
          className="h-10 w-[calc(50%-4px)] border-slate-300 bg-white sm:w-36"
          value={cityInput}
          onChange={(event) => setCityInput(event.target.value)}
        />
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger
            aria-label="Shipment status"
            className="h-10 w-[calc(50%-4px)] border-slate-300 bg-white sm:w-44"
          >
            <SelectValue placeholder="Shipment status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Shipment status</SelectItem>
            {APPOINTMENT_STATUS_FILTERS.map((value) => (
              <SelectItem key={value} value={value}>
                {getShipmentStatusLabel(value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              className="h-10 w-[calc(50%-4px)] justify-between border-slate-300 bg-white font-normal sm:w-auto"
            >
              <span className="truncate">{dateRangeLabel}</span>
              <ChevronDown className="ml-2 h-4 w-4 text-slate-400" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-64 space-y-3">
            <p className="text-xs text-slate-500">
              Filters by the delivery-by (appointment) date.
            </p>
            <div className="space-y-1.5">
              <Label htmlFor="pdd-from" className="text-xs font-semibold">From</Label>
              <Input
                id="pdd-from"
                type="date"
                value={pddFrom}
                onChange={(event) => setPddFrom(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pdd-to" className="text-xs font-semibold">To</Label>
              <Input
                id="pdd-to"
                type="date"
                value={pddTo}
                min={pddFrom || undefined}
                onChange={(event) => setPddTo(event.target.value)}
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-full"
              onClick={() => {
                setPddFrom("");
                setPddTo("");
              }}
            >
              Clear dates
            </Button>
          </PopoverContent>
        </Popover>
        <label className="flex h-10 cursor-pointer items-center gap-3 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700">
          Show only expired POs
          <button
            type="button"
            role="switch"
            aria-checked={expiredOnly}
            aria-label="Show only expired POs"
            onClick={() => setExpiredOnly((prev) => !prev)}
            className={cn(
              "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
              expiredOnly ? "bg-primary" : "bg-slate-300"
            )}
          >
            <span
              className={cn(
                "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
                expiredOnly ? "translate-x-4" : "translate-x-0.5"
              )}
            />
          </button>
        </label>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm font-medium text-destructive">
          {error}
        </div>
      )}

      {/* Desktop table */}
      <div className="relative hidden overflow-hidden rounded-xl border border-slate-200 bg-white md:block">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-slate-50 text-sm text-slate-700">
              <tr>
                {canBook && (
                  <th className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      aria-label="Select all LRs on this page"
                      className="h-4 w-4 accent-primary"
                      checked={allSelected}
                      disabled={rows.length === 0}
                      onChange={toggleAll}
                    />
                  </th>
                )}
                <th className="px-4 py-3 font-semibold">LR details</th>
                <th className="px-4 py-3 font-semibold">Consignee details</th>
                <th className="px-4 py-3 font-semibold">PO expiry date</th>
                <th className="px-4 py-3 font-semibold">Shipment status</th>
                <th className="px-4 py-3 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && rows.length === 0 && (
                <tr data-testid="appointments-loading-skeleton">
                  <td colSpan={canBook ? 6 : 5} className="px-4 py-8">
                    <div className="space-y-2.5">
                      {[0, 1, 2].map((idx) => (
                        <div
                          key={idx}
                          className="h-10 w-full rounded-lg bg-slate-100 animate-pulse"
                        />
                      ))}
                    </div>
                  </td>
                </tr>
              )}
              {rows.length === 0 && !loading && (
                <tr>
                  <td colSpan={canBook ? 6 : 5} className="px-4 py-16 text-center text-sm text-slate-500">
                    No LRs in this tab.
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.shipment_id} className="hover:bg-slate-50/70">
                  {canBook && (
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label="Select LR"
                        className="h-4 w-4 accent-primary"
                        checked={selectedIds.has(row.shipment_id)}
                        onChange={() => toggleRow(row.shipment_id)}
                      />
                    </td>
                  )}
                  <td className="px-4 py-3"><LrCell row={row} /></td>
                  <td className="max-w-[320px] px-4 py-3"><ConsigneeCell row={row} /></td>
                  <td className="px-4 py-3"><PoExpiryCell row={row} /></td>
                  <td className="px-4 py-3"><StatusCell row={row} /></td>
                  <td className="px-4 py-3">
                    <RowActions
                      row={row}
                      canBook={canBook}
                      isBookedTab={isBookedTab}
                      onBook={(target) => setDialogRows([target])}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile cards */}
      <div className="space-y-3 md:hidden">
        {loading && rows.length === 0 && (
          <div className="space-y-2.5 py-4">
            {[0, 1].map((idx) => (
              <div
                key={idx}
                className="h-24 w-full rounded-xl bg-slate-100 animate-pulse"
              />
            ))}
          </div>
        )}
        {!loading && rows.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            No LRs in this tab.
          </div>
        )}
        {!loading &&
          rows.map((row) => (
            <div key={row.shipment_id} className="space-y-3 rounded-xl border border-slate-200 bg-white p-3">
              <div className="flex items-start justify-between gap-2">
                <LrCell row={row} />
                <StatusCell row={row} />
              </div>
              <ConsigneeCell row={row} />
              <div className="flex items-center justify-between border-t border-slate-100 pt-2">
                <PoExpiryCell row={row} />
                <RowActions
                  row={row}
                  canBook={canBook}
                  isBookedTab={isBookedTab}
                  onBook={(target) => setDialogRows([target])}
                />
              </div>
            </div>
          ))}
      </div>

      {/* Pagination */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3 text-sm text-slate-600">
        <span>
          Showing {firstRow}-{lastRow} of {total}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            aria-label="Previous page"
            className="h-8 w-8"
            disabled={page <= 1}
            onClick={() => setPage((prev) => prev - 1)}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-[2rem] rounded bg-primary px-2 py-1 text-center text-xs font-bold text-primary-foreground">
            {page}
          </span>
          <Button
            variant="outline"
            size="icon"
            aria-label="Next page"
            className="h-8 w-8"
            disabled={page >= pageCount}
            onClick={() => setPage((prev) => prev + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <span>Rows per page</span>
          <Select value={String(size)} onValueChange={(value) => setSize(Number(value))}>
            <SelectTrigger aria-label="Rows per page" className="h-8 w-20">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {APPOINTMENT_PAGE_SIZES.map((value) => (
                <SelectItem key={value} value={String(value)}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <BookAppointmentDialog
        open={dialogRows.length > 0}
        rows={dialogRows}
        onOpenChange={(open) => {
          if (!open) setDialogRows([]);
        }}
        onBooked={() => {
          setSelectedIds(new Set());
          setRefreshKey((key) => key + 1);
          window.dispatchEvent(new CustomEvent("appointments-updated"));
        }}
      />
    </div>
  );
}
