"use client";

import type {
  CodRemittanceRead,
} from
  "@/api_client";
import {
  RemittancesService,
} from
  "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
} from "@/lib/utils";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Headphones,
  Loader2,
  Package,
  Receipt,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

interface RemittanceAwbBreakdownItem {
  shipment_id?: string | null;
  tracking_id: string;
  order_reference_id?: string | null;
  amount_collected: number;
}

function formatInrAmount(val: number | undefined | null): string {
  const num = Number(val ?? 0);
  return num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getRemittanceTotal(remit: CodRemittanceRead | null): number {
  if (!remit) return 0;
  return Number(remit.total_remittance ?? 0);
}

function getRemittanceOrdersCount(
  remit: CodRemittanceRead | null,
  fallbackCount: number
): number {
  if (!remit) return fallbackCount;
  const count = Number(remit.total_orders ?? 0);
  return count > 0 ? count : fallbackCount;
}

async function downloadRemittanceCsvBlob(
  identifier: string,
  remittanceNumber: string
): Promise<void> {
  const { OpenAPI } = await import("@/api_client");
  const axios = (await import("axios")).default;
  const endpointUrl = ["/api/v1/remittances/", identifier, "/csv"].join("");

  const headers =
    typeof OpenAPI.HEADERS === "function"
      ? await OpenAPI.HEADERS({
          method: "GET",
          url: endpointUrl,
        })
      : OpenAPI.HEADERS || {};

  const response = await axios.get(endpointUrl, {
    headers,
    responseType: "blob",
  });

  const blob = new Blob([response.data], {
    type: String(response.headers["content-type"] || "text/csv"),
  });
  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  anchor.download = ["remittance_", remittanceNumber, "_awb.csv"].join("");
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(downloadUrl);
  document.body.removeChild(anchor);
}

export default function RemittanceDetailPage() {
  const params = useParams();
  const identifier = decodeURIComponent(String(params?.id || ""));
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  /** Staff read every merchant's batches; merchants need the help link instead. */
  const isStaff = capabilities.isStaff;

  const [remittance, setRemittance] = useState<CodRemittanceRead | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [downloading, setDownloading] = useState<boolean>(false);
  const [awbSearch, setAwbSearch] = useState<string>("");

  const fetchDetail = useCallback(async () => {
    if (!tenantSlug || !identifier) return;
    setLoading(true);
    try {
      const detail = await RemittancesService.getRemittanceDetail(
        identifier,
        tenantSlug
      );
      setRemittance(detail);
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Unable to load remittance details.")
      );
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, identifier]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const breakdownItems = useMemo<RemittanceAwbBreakdownItem[]>(() => {
    if (!remittance) return [];
    const raw = Array.isArray(remittance.shipment_breakdown)
      ? remittance.shipment_breakdown
      : [];
    if (raw.length > 0) {
      return raw.map((entry: Record<string, unknown>) => ({
        shipment_id: entry.shipment_id ? String(entry.shipment_id) : null,
        tracking_id: String(
          entry.tracking_id || entry.awb || remittance.remittance_number
        ),
        order_reference_id: entry.order_reference_id
          ? String(entry.order_reference_id)
          : null,
        amount_collected: Number(entry.amount_collected ?? 0),
      }));
    }
    return [
      {
        shipment_id: null,
        tracking_id: remittance.remittance_number,
        order_reference_id: remittance.bank_utr,
        amount_collected: getRemittanceTotal(remittance),
      },
    ];
  }, [remittance]);

  const filteredItems = useMemo(() => {
    const q = awbSearch.trim().toLowerCase();
    if (!q) return breakdownItems;
    return breakdownItems.filter(
      (item) =>
        item.tracking_id.toLowerCase().includes(q) ||
        (item.order_reference_id || "").toLowerCase().includes(q)
    );
  }, [breakdownItems, awbSearch]);

  const handleDownloadCsv = async () => {
    if (!remittance) return;
    setDownloading(true);
    try {
      await downloadRemittanceCsvBlob(
        remittance.remittance_number,
        remittance.remittance_number
      );
      toast.success("Downloaded AWB remittance CSV.");
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to download remittance CSV.")
      );
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-500 gap-2">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span className="text-sm font-medium">
          Loading transaction details
        </span>
      </div>
    );
  }

  if (!remittance) {
    return (
      <div className="max-w-3xl mx-auto py-16 text-center space-y-4">
        <p className="text-base font-semibold text-slate-800">
          Remittance record not found
        </p>
        <Button asChild variant="outline" size="sm">
          <Link href={routeTo("/finances/remittances")}>
            Back to Remittances
          </Link>
        </Button>
      </div>
    );
  }

  const stateUpper = (remittance.state || "COMPLETED").toUpperCase();
  const isCompleted = stateUpper === "COMPLETED";
  const formattedDate = safeFormatDate(
    remittance.processed_date,
    "d MMM, yyyy"
  );
  const amountValue = getRemittanceTotal(remittance);
  const ordersCount = getRemittanceOrdersCount(
    remittance,
    breakdownItems.length
  );

  return (
    <div className="max-w-4xl space-y-6 pb-12">
      <div className="flex items-center gap-3">
        <Button
          asChild
          variant="outline"
          size="icon"
          className="h-9 w-9 rounded-lg border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
        >
          <Link
            href={routeTo("/finances/remittances")}
            aria-label="Back to Remittances"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <span className="text-sm font-semibold text-slate-800">
          Transaction Details
        </span>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white shadow-2xs">
              <Receipt className="h-6 w-6 text-slate-700" />
            </div>
            <div>
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 font-heading break-all">
                {remittance.remittance_number}
              </h1>
              <p className="text-xs text-slate-500 font-mono mt-0.5">
                UTR: {remittance.bank_utr}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <Badge
              variant="outline"
              className={cn(
                "rounded-full px-3 py-0.5 text-xs font-medium",
                isCompleted
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-amber-50 text-amber-700 border-amber-200"
              )}
            >
              {isCompleted ? "Completed" : remittance.state}
            </Badge>

            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
              <Calendar className="h-3.5 w-3.5 text-slate-500" />
              Processed On: {formattedDate}
            </span>
            {isStaff && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
                data-testid="remittance-detail.merchant"
              >
                Merchant: {remittance.merchant_email || "—"}
              </span>
            )}
          </div>
        </div>

        {!isStaff && (
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-9 gap-2 border-slate-200 bg-white text-slate-800 hover:bg-slate-50 self-start"
        >
          <Link href={routeTo("/support")}>
            <Headphones className="h-4 w-4 text-slate-600" />
            Need Help?
          </Link>
        </Button>
        )}
      </div>

      <Card className="border-slate-200 shadow-xs bg-white">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
              <FileSpreadsheet className="h-4 w-4" />
            </div>
            <CardTitle className="text-base font-semibold text-slate-900">
              Remittance Details
            </CardTitle>
          </div>

          <button
            type="button"
            onClick={handleDownloadCsv}
            disabled={downloading}
            data-testid="remittance-detail.actions.download-csv"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline disabled:opacity-50"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Download AWB data
          </button>
        </CardHeader>

        <CardContent>
          <div className="rounded-xl bg-slate-50 border border-slate-100 p-6">
            <div className="flex items-center justify-center gap-3.5 py-2">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500">
                  Remittance Amount
                </p>
                <p className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
                  ₹ {formatInrAmount(amountValue)}
                </p>
              </div>
            </div>

            <div className="my-5 border-t border-slate-200" />

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
              <div>
                <p className="text-xs font-semibold text-slate-700">
                  <span>
                    Total Orders
                  </span>
                </p>
                <p className="text-sm font-medium text-slate-900 mt-0.5">
                  {ordersCount}
                </p>
              </div>

              <div>
                <p className="text-xs font-semibold text-slate-700">
                  Remittance Date
                </p>
                <p className="text-sm font-medium text-slate-900 mt-0.5">
                  {formattedDate}
                </p>
              </div>

              <div className="col-span-2 sm:col-span-1">
                <p className="text-xs font-semibold text-slate-700">
                  Bank UTR Reference
                </p>
                <p className="text-sm font-mono font-medium text-slate-900 mt-0.5">
                  {remittance.bank_utr}
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200 shadow-xs bg-white">
        <CardHeader className="pb-3 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
              <Package className="h-4 w-4" />
            </div>
            <CardTitle className="text-base font-semibold text-slate-900">
              AWB Numbers
            </CardTitle>
          </div>

          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={awbSearch}
              onChange={(e) => setAwbSearch(e.target.value)}
              placeholder="Search By AWB"
              className="h-10 pl-9 bg-white border-slate-200 text-sm"
            />
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <Table>
              <TableHeader className="bg-slate-50">
                <TableRow className="border-slate-200">
                  <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3 pl-4">
                    AWB NUMBER
                  </TableHead>
                  <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3 pr-4">
                    AMOUNT COLLECTED
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredItems.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={2}
                      className="py-8 text-center text-xs text-slate-500"
                    >
                      No matching AWB numbers found in this remittance batch.
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredItems.map((item, idx) => {
                    const targetHref = item.shipment_id
                      ? routeTo(["/shipments/", item.shipment_id].join(""))
                      : routeTo(["/track/", item.tracking_id].join(""));

                    return (
                      <TableRow
                        key={[item.tracking_id, String(idx)].join("-")}
                        className="border-slate-100 hover:bg-slate-50"
                      >
                        <TableCell className="py-3.5 pl-4">
                          <Link
                            href={targetHref}
                            className="text-sm font-medium text-primary hover:underline"
                          >
                            {item.tracking_id}
                          </Link>
                          {item.order_reference_id && (
                            <p className="text-[11px] text-slate-500 mt-0.5">
                              Ref: {item.order_reference_id}
                            </p>
                          )}
                        </TableCell>
                        <TableCell className="py-3.5 pr-4 text-sm font-medium text-slate-900">
                          ₹ {formatInrAmount(item.amount_collected)}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 text-xs text-slate-600">
            <span>
              Showing{" "}
              <strong className="text-slate-900">
                1 - {filteredItems.length}
              </strong>{" "}
              of{" "}
              <strong className="text-slate-900">
                {filteredItems.length}
              </strong>
            </span>
            <div className="flex items-center gap-3">
              <span>Show 50 per page</span>
              <span className="inline-flex h-7 w-7 items-center justify-center rounded border border-primary/30 bg-primary/10 text-primary font-semibold">
                1
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
