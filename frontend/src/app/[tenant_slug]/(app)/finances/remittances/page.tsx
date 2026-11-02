"use client";

import type {
  CodRemittanceCreate,
  CodRemittancePreview,
  CodRemittanceRead,
  UserRead,
} from
  "@/api_client";
import {
  RemittancesService,
  UserRole,
  UsersService,
} from
  "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  cn,
  extractApiErrorMessage,
  safeFormatDate,
  toIstDateTimeLocalValue,
} from "@/lib/utils";
import {
  ArrowUpDown,
  Calendar,
  HelpCircle,
  Landmark,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

/** Length of the `yyyy-MM-dd` prefix of an ISO date-time. */
const ISO_DATE_LENGTH = 10;

function formatInrCurrency(val: number | undefined | null): string {
  const num = Number(val ?? 0);
  return num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getRemittanceAmount(row: CodRemittanceRead): number {
  return Number(row.total_remittance ?? 0);
}

function getRemittanceOrders(row: CodRemittanceRead): number {
  return Number(row.total_orders ?? 0);
}

function formatStateLabel(rawState: string | undefined): string {
  if (!rawState) return "Completed";
  const upper = rawState.toUpperCase();
  if (upper === "COMPLETED") return "Completed";
  if (upper === "PENDING") return "Pending";
  return rawState;
}

/**
 * Today's date as `yyyy-MM-dd` in IST. `toISOString()` is UTC and would default
 * the batch to yesterday between 00:00 and 05:30 IST.
 */
function todayIstDate(): string {
  return toIstDateTimeLocalValue(new Date().toISOString()).slice(0, ISO_DATE_LENGTH);
}

export default function RemittancesListPage() {
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const canManageFinance = capabilities.canManageFinance;
  /** Staff see every merchant's batches, so each row names its merchant. */
  const showMerchant = capabilities.isStaff;

  const [remittances, setRemittances] = useState<CodRemittanceRead[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [processedDate, setProcessedDate] = useState<string>("");
  const [sortAsc, setSortAsc] = useState<boolean>(false);

  const [dialogOpen, setDialogOpen] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [bankUtr, setBankUtr] = useState<string>("");
  const [customNumber, setCustomNumber] = useState<string>("");
  const [batchDate, setBatchDate] = useState<string>(todayIstDate);
  const [merchants, setMerchants] = useState<UserRead[]>([]);
  const [merchantsLoading, setMerchantsLoading] = useState<boolean>(false);
  const [merchantId, setMerchantId] = useState<string>("");
  const [preview, setPreview] = useState<CodRemittancePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);
  const [selectedShipmentIds, setSelectedShipmentIds] = useState<string[]>([]);

  const loadMerchantPreview = useCallback(
    async (targetMerchantId: string, selectedIds?: string[]) => {
      if (!tenantSlug || !targetMerchantId) {
        setPreview(null);
        setSelectedShipmentIds([]);
        return;
      }
      setPreviewLoading(true);
      try {
        const res = await RemittancesService.previewPendingRemittance(
          targetMerchantId,
          selectedIds,
          tenantSlug
        );
        setPreview(res);
        if (selectedIds === undefined) {
          setSelectedShipmentIds(
            (res.lines || []).map((line) => line.shipment_id)
          );
        }
      } catch (err: unknown) {
        toast.error(
          extractApiErrorMessage(err, "Failed to load pending COD preview.")
        );
      } finally {
        setPreviewLoading(false);
      }
    },
    [tenantSlug]
  );

  useEffect(() => {
    if (dialogOpen && merchantId) {
      void loadMerchantPreview(merchantId);
    } else if (!merchantId) {
      setPreview(null);
      setSelectedShipmentIds([]);
    }
  }, [dialogOpen, merchantId, loadMerchantPreview]);

  const handleToggleShipment = useCallback(
    async (shipmentId: string, checked: boolean) => {
      const nextIds = checked
        ? Array.from(new Set([...selectedShipmentIds, shipmentId]))
        : selectedShipmentIds.filter((id) => id !== shipmentId);
      setSelectedShipmentIds(nextIds);
      if (merchantId && nextIds.length > 0) {
        await loadMerchantPreview(merchantId, nextIds);
      }
    },
    [merchantId, selectedShipmentIds, loadMerchantPreview]
  );

  const fetchRemittances = useCallback(async () => {
    if (!tenantSlug) return;
    setLoading(true);
    try {
      const searchParam = searchQuery.trim() ? searchQuery.trim() : null;
      const dateParam = processedDate ? processedDate : null;
      const rows = await RemittancesService.listRemittances(
        searchParam,
        dateParam,
        tenantSlug
      );
      setRemittances(rows || []);
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to load remittances list.")
      );
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, searchQuery, processedDate]);

  useEffect(() => {
    fetchRemittances();
  }, [fetchRemittances]);

  const filteredRemittances = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const list = remittances.filter((item) => {
      if (!q) return true;
      const numMatch = item.remittance_number.toLowerCase().includes(q);
      const utrMatch = (item.bank_utr || "").toLowerCase().includes(q);
      return numMatch || utrMatch;
    });

    const sorted = list.slice().sort((a, b) => {
      const tA = new Date(a.processed_date).getTime();
      const tB = new Date(b.processed_date).getTime();
      return sortAsc ? tA - tB : tB - tA;
    });
    return sorted;
  }, [remittances, searchQuery, sortAsc]);

  const fetchMerchants = useCallback(async () => {
    if (!tenantSlug) return;
    setMerchantsLoading(true);
    try {
      const users = await UsersService.listUsersInTenant(tenantSlug);
      setMerchants(
        (users || []).filter((u) => u.role === UserRole.CUSTOMER)
      );
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to load merchants."));
    } finally {
      setMerchantsLoading(false);
    }
  }, [tenantSlug]);

  useEffect(() => {
    if (dialogOpen && canManageFinance) {
      fetchMerchants();
    }
  }, [dialogOpen, canManageFinance, fetchMerchants]);

  const handleCreateBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!merchantId) {
      toast.error("Please select the merchant being paid.");
      return;
    }
    if (!preview) {
      toast.error("Pending COD preview has not loaded yet.");
      return;
    }
    if (preview.payout_blocked_reason) {
      toast.error(preview.payout_blocked_reason);
      return;
    }
    if (selectedShipmentIds.length === 0) {
      toast.error("Please select at least one delivered COD order to remit.");
      return;
    }
    if (!bankUtr.trim()) {
      toast.error("Please enter the Bank Transaction ID (UTR).");
      return;
    }
    setSubmitting(true);
    try {
      const payload: CodRemittanceCreate = {
        merchant_user_id: merchantId,
        bank_utr: bankUtr.trim(),
        remittance_number: customNumber.trim() || null,
        processed_date: batchDate || null,
        state: "COMPLETED",
        shipment_ids: selectedShipmentIds,
        expected_total: preview.total,
      };

      const created = await RemittancesService.createRemittance(
        payload,
        tenantSlug
      );
      toast.success(
        [
          "Remittance batch ",
          created.remittance_number,
          " processed for ",
          String(created.total_orders),
          " order(s).",
        ].join("")
      );
      setDialogOpen(false);
      setBankUtr("");
      setCustomNumber("");
      setMerchantId("");
      setPreview(null);
      setSelectedShipmentIds([]);
      await fetchRemittances();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Unable to process remittance batch.")
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 pb-10">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-heading">
            Remittances
          </h1>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 border border-slate-200">
            <HelpCircle className="h-3.5 w-3.5 text-primary" />
            Learn More
          </span>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchRemittances}
            disabled={loading}
            className="h-9 gap-1.5"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", loading && "animate-spin")}
            />
            Refresh
          </Button>

          {canManageFinance && (
            <Button
              size="sm"
              onClick={() => setDialogOpen(true)}
              className="h-9 gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <Plus className="h-4 w-4" />
              Process Remittance Batch
            </Button>
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by Remittance Number"
            className="min-w-0 w-full h-10 pl-9 pr-8 bg-white border-slate-200 text-sm"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              aria-label="Clear search"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="relative flex min-w-0 items-center">
            <Calendar className="pointer-events-none absolute left-3 h-4 w-4 text-slate-500" />
            <Input
              type="date"
              value={processedDate}
              onChange={(e) => setProcessedDate(e.target.value)}
              aria-label="Processed On"
              className="h-10 pl-9 pr-3 bg-white border-slate-200 text-sm w-44 min-w-0 max-w-full"
            />
          </div>
          {processedDate && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setProcessedDate("")}
              className="h-9 px-2.5 text-xs text-slate-600 hover:text-slate-900"
            >
              Reset Date
            </Button>
          )}
        </div>
      </div>

      <Card className="border-slate-200 shadow-xs overflow-hidden bg-white">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-slate-500 gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <span className="text-sm font-medium">
                Loading remittances
              </span>
            </div>
          ) : filteredRemittances.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <div className="h-12 w-12 rounded-full bg-slate-100 flex items-center justify-center mb-3">
                <Landmark className="h-6 w-6 text-slate-400" />
              </div>
              <p className="text-base font-semibold text-slate-800">
                No remittance records found
              </p>
              <p className="text-xs text-slate-500 mt-1 max-w-md">
                Remittance settlements and UTR transaction references will appear
                here once processed.
              </p>
            </div>
          ) : (
            <>
              <div className="hidden md:block">
                <Table>
                  <TableHeader className="bg-slate-50">
                    <TableRow className="border-slate-200">
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5 pl-6">
                        REMITTANCE NUMBER
                      </TableHead>
                      {showMerchant && (
                        <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                          MERCHANT
                        </TableHead>
                      )}
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        <button
                          type="button"
                          onClick={() => setSortAsc((prev) => !prev)}
                          className="inline-flex items-center gap-1 hover:text-slate-800"
                        >
                          DATE
                          <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
                        </button>
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        BANK&apos;S TRANSACTION ID
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        STATE
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5 pr-6">
                        <span>
                          TOTAL REMITTANCE
                        </span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredRemittances.map((r) => {
                      const stateLabel = formatStateLabel(r.state);
                      const isCompleted =
                        stateLabel.toLowerCase() === "completed";
                      const amountVal = getRemittanceAmount(r);
                      const detailHref = routeTo(
                        ["/finances/remittances/", r.remittance_number].join("")
                      );

                      return (
                        <TableRow
                          key={r.id}
                          className="border-slate-100 hover:bg-slate-50 transition-colors"
                          data-testid={`remittances.row.${r.remittance_number}`}
                        >
                          <TableCell className="py-3.5 pl-6 font-medium">
                            <Link
                              href={detailHref}
                              className="text-primary hover:underline font-medium text-sm"
                            >
                              {r.remittance_number}
                            </Link>
                          </TableCell>
                          {showMerchant && (
                            <TableCell
                              className="py-3.5 text-sm text-slate-700"
                              data-testid={`remittances.row.${r.remittance_number}.merchant`}
                            >
                              {r.merchant_email || "—"}
                            </TableCell>
                          )}
                          <TableCell className="py-3.5 text-sm font-medium text-slate-800">
                            {safeFormatDate(r.processed_date, "d MMM, yyyy")}
                          </TableCell>
                          <TableCell className="py-3.5 text-sm text-slate-600 font-mono">
                            {r.bank_utr}
                          </TableCell>
                          <TableCell className="py-3.5">
                            <Badge
                              variant="outline"
                              className={cn(
                                "rounded-full px-2.5 py-0.5 text-xs font-medium",
                                isCompleted
                                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                  : "bg-amber-50 text-amber-700 border-amber-200"
                              )}
                            >
                              {stateLabel}
                            </Badge>
                          </TableCell>
                          <TableCell className="py-3.5 pr-6 text-sm font-medium text-slate-900">
                            <span data-testid={`remittances.row.${r.remittance_number}.total`}>₹ {formatInrCurrency(amountVal)}</span>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>

              <div className="md:hidden divide-y divide-slate-100">
                {filteredRemittances.map((r) => {
                  const stateLabel = formatStateLabel(r.state);
                  const isCompleted = stateLabel.toLowerCase() === "completed";
                  const amountVal = getRemittanceAmount(r);
                  const orderCount = getRemittanceOrders(r);
                  const detailHref = routeTo(
                    ["/finances/remittances/", r.remittance_number].join("")
                  );

                  return (
                    <div key={r.id} className="p-4 space-y-2.5" data-testid={`remittances.row.${r.remittance_number}`}>
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <Link
                            href={detailHref}
                            className="text-sm font-semibold text-primary hover:underline break-all"
                          >
                            {r.remittance_number}
                          </Link>
                          <p className="text-xs text-slate-500 mt-0.5">
                            {safeFormatDate(r.processed_date, "d MMM, yyyy")}
                          </p>
                          {showMerchant && r.merchant_email && (
                            <p className="text-xs text-slate-600 mt-0.5 break-all">
                              {r.merchant_email}
                            </p>
                          )}
                        </div>
                        <Badge
                          variant="outline"
                          className={cn(
                            "rounded-full px-2.5 py-0.5 text-xs font-medium shrink-0",
                            isCompleted
                              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                              : "bg-amber-50 text-amber-700 border-amber-200"
                          )}
                        >
                          {stateLabel}
                        </Badge>
                      </div>

                      <div className="flex items-center justify-between text-xs text-slate-600 pt-1">
                        <span className="font-mono">
                          UTR: {r.bank_utr}
                        </span>
                        <span className="text-sm font-bold text-slate-900">
                          <span data-testid={`remittances.row.${r.remittance_number}.total`}>₹ {formatInrCurrency(amountVal)}</span>
                        </span>
                      </div>
                      {orderCount > 0 && (
                        <div className="text-[11px] text-slate-500">
                          <span>
                            Orders settled: {orderCount}
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md overflow-x-hidden">
          <DialogHeader className="min-w-0">
            <DialogTitle className="font-heading">
              Process Remittance Batch
            </DialogTitle>
            <DialogDescription>
              Record one bank NEFT/IMPS/RTGS payout to a merchant. Tick the
              delivered COD orders this transfer pays (orders already remitted,
              settled to the wallet, or returned to origin are never listed);
              amounts and the payout total are computed by the server.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleCreateBatch} className="min-w-0 space-y-4 py-2">
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="remit-merchant">Merchant</Label>
              <Select value={merchantId} onValueChange={setMerchantId}>
                <SelectTrigger id="remit-merchant" className="min-w-0 w-full">
                  <SelectValue
                    placeholder={
                      merchantsLoading ? "Loading merchants" : "Select merchant"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {merchants.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.full_name
                        ? [m.full_name, " (", m.email, ")"].join("")
                        : m.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!merchantsLoading && merchants.length === 0 && (
                <p className="text-xs text-slate-500">
                  No customer accounts found in this workspace.
                </p>
              )}
            </div>

            {merchantId && (
              <div
                className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 space-y-2.5 text-xs"
                data-testid="remittances.preview-panel"
              >
                {previewLoading && !preview ? (
                  <div className="flex items-center gap-2 text-slate-600 py-2">
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                    <span>Loading eligible COD shipments…</span>
                  </div>
                ) : preview ? (
                  <>
                    <div className="flex items-center justify-between text-slate-700">
                      <span className="font-medium">Merchant Wallet Balance</span>
                      <span
                        className={cn(
                          "font-semibold",
                          preview.wallet_balance < 0
                            ? "text-rose-600"
                            : "text-emerald-700"
                        )}
                        data-testid="remittances.preview-wallet-balance"
                      >
                        ₹ {formatInrCurrency(preview.wallet_balance)}
                      </span>
                    </div>

                    {preview.payout_blocked_reason && (
                      <div
                        className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-2 text-rose-700 font-medium"
                        data-testid="remittances.payout-blocked-banner"
                      >
                        {preview.payout_blocked_reason}
                      </div>
                    )}

                    {preview.lines.length === 0 ? (
                      <p
                        className="text-slate-500 py-1"
                        data-testid="remittances.preview-empty"
                      >
                        No delivered unremitted COD shipments found for this merchant.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                          Eligible Delivered COD Orders ({preview.lines.length})
                        </div>
                        <div className="max-h-40 overflow-y-auto divide-y divide-slate-200/70 rounded border border-slate-200 bg-white">
                          {preview.lines.map((line) => {
                            const checked = selectedShipmentIds.includes(
                              line.shipment_id
                            );
                            return (
                              <label
                                key={line.shipment_id}
                                className="flex items-center justify-between gap-2 px-2.5 py-1.5 cursor-pointer hover:bg-slate-50"
                                data-testid={`remittances.pending-awb.${line.tracking_id}`}
                              >
                                <span className="flex items-center gap-2 min-w-0">
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(e) =>
                                      void handleToggleShipment(
                                        line.shipment_id,
                                        e.target.checked
                                      )
                                    }
                                    className="h-3.5 w-3.5 rounded border-slate-300 text-primary focus:ring-primary"
                                  />
                                  <span className="font-mono font-medium text-slate-800 truncate">
                                    {line.tracking_id}
                                  </span>
                                  {line.order_reference_id && (
                                    <span className="text-slate-400 truncate">
                                      ({line.order_reference_id})
                                    </span>
                                  )}
                                </span>
                                <span className="font-semibold text-slate-900 shrink-0">
                                  ₹ {formatInrCurrency(line.amount)}
                                </span>
                              </label>
                            );
                          })}
                        </div>
                        <div
                          className="flex items-center justify-between pt-1 border-t border-slate-200 text-slate-900 font-semibold"
                          data-testid="remittances.preview-total"
                        >
                          <span>
                            Selected:{" "}
                            {selectedShipmentIds.length === 0
                              ? 0
                              : preview.selected_count}{" "}
                            order(s)
                          </span>
                          <span>
                            Payout Total: ₹{" "}
                            {selectedShipmentIds.length === 0
                              ? "0.00"
                              : formatInrCurrency(preview.total)}
                          </span>
                        </div>
                      </div>
                    )}
                  </>
                ) : null}
              </div>
            )}

            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="bank-utr">
                Bank&apos;s Transaction ID (UTR)
              </Label>
              <Input
                id="bank-utr"
                value={bankUtr}
                onChange={(e) => setBankUtr(e.target.value)}
                placeholder="e.g. AXISP00847542539"
                className="min-w-0 w-full"
                required
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 min-w-0">
              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="processed-date">
                  Processed Date
                </Label>
                <Input
                  id="processed-date"
                  type="date"
                  value={batchDate}
                  onChange={(e) => setBatchDate(e.target.value)}
                  className="min-w-0 w-full"
                  required
                />
              </div>

              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="remit-num">
                  Remittance Number (Optional)
                </Label>
                <Input
                  id="remit-num"
                  value={customNumber}
                  onChange={(e) => setCustomNumber(e.target.value)}
                  placeholder="Auto-generated if blank"
                  className="min-w-0 w-full"
                />
              </div>
            </div>

            <DialogFooter className="pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  submitting ||
                  previewLoading ||
                  !preview ||
                  Boolean(preview.payout_blocked_reason) ||
                  selectedShipmentIds.length === 0
                }
                className="bg-primary text-primary-foreground hover:bg-primary/90"
              >
                {submitting && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Create Settlement Batch
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
