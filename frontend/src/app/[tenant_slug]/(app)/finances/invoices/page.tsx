"use client";

import type {
  BillingInvoiceRead,
} from
  "@/api_client";
import {
  InvoicesService,
} from
  "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import {
  documentTypeLabel,
  isWithinDateRange,
} from "@/components/finance/document-filters";
import { LearnMore } from "@/components/finance/learn-more";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  buildQueryCacheKey,
  getCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import {
  cn,
  extractApiErrorMessage,
  safeFormatDate,
} from "@/lib/utils";
import {
  ArrowUpDown,
  Boxes,
  ChevronDown,
  Download,
  FileSpreadsheet,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Truck,
  X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

type NoteTabType = "ALL" | "INVOICE" | "CREDIT_NOTE" | "DEBIT_NOTE";

const NOTE_TABS: Array<{ label: string; value: NoteTabType }> = [
  { label: "All Documents", value: "ALL" },
  { label: "Invoice List", value: "INVOICE" },
  { label: "Credit Notes", value: "CREDIT_NOTE" },
  { label: "Debit Notes", value: "DEBIT_NOTE" },
];

const getTabTestId = (val: NoteTabType) => {
  if (val === "ALL") return "invoices.tabs.all";
  if (val === "INVOICE") return "invoices.tabs.invoices";
  if (val === "DEBIT_NOTE") return "invoices.tabs.debit-notes";
  return "invoices.tabs.credit-notes";
};

/** Column labels per tab: Delhivery One calls a credit / debit note's id "Note ID". */
const NOTE_TAB_COLUMNS: Record<NoteTabType, { id: string; date: string; amount: string }> = {
  ALL: { id: "DOCUMENT ID", date: "DATE", amount: "AMOUNT" },
  INVOICE: { id: "INVOICE ID", date: "INVOICE DATE", amount: "INVOICE AMOUNT" },
  CREDIT_NOTE: { id: "NOTE ID", date: "ISSUED DATE", amount: "TOTAL AMOUNT" },
  DEBIT_NOTE: { id: "NOTE ID", date: "ISSUED DATE", amount: "TOTAL AMOUNT" },
};


function formatInrValue(val: number | undefined | null): string {
  const num = Number(val ?? 0);
  return num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getInvoiceTotalValue(inv: BillingInvoiceRead): number {
  return Number(inv.total_amount ?? 0);
}

async function downloadInvoiceFileBlob(
  endpointPath: string,
  filename: string
): Promise<void> {
  const { OpenAPI } = await import("@/api_client");
  const axios = (await import("axios")).default;

  const headers =
    typeof OpenAPI.HEADERS === "function"
      ? await OpenAPI.HEADERS({
          method: "GET",
          url: endpointPath,
        })
      : OpenAPI.HEADERS || {};

  const response = await axios.get(endpointPath, {
    headers,
    responseType: "blob",
  });

  const blob = new Blob([response.data], {
    type: String(
      response.headers["content-type"] || "application/octet-stream"
    ),
  });
  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(downloadUrl);
  document.body.removeChild(anchor);
}

/** Plain-language rules behind the "Learn More" pill (Delhivery One help slug `invoices`). */
const INVOICES_HELP_POINTS: readonly string[] = [
  "A GST tax invoice (SAC 996812) is issued for every shipment you book; prepaid invoices are already paid from your wallet and can be viewed and downloaded.",
  "A credit note is issued when you are refunded (cancellation, accepted weight claim, lower re-weigh); a debit note when an extra charge is added (re-weigh, RTO, exception charges).",
  "Open a document to see its AWB, charges and tax split, or download the PDF and the AWB-wise transaction CSV.",
  "Add your company name and GSTIN in My profile so they are printed as Bill To and you can claim input tax credit.",
];

/** Small coloured pill telling an invoice from a credit / debit note. */
function DocumentTypeBadge({ noteType }: { noteType: string | undefined }) {
  const label = documentTypeLabel(noteType);
  return (
    <Badge
      variant="outline"
      className={cn(
        "rounded-full px-2 py-0 text-[10px] font-semibold",
        noteType === "CREDIT_NOTE"
          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : noteType === "DEBIT_NOTE"
            ? "bg-amber-50 text-amber-800 border-amber-200"
            : "bg-slate-100 text-slate-700 border-slate-200"
      )}
    >
      {label}
    </Badge>
  );
}

function renderServiceTypeCell(serviceType: string | undefined) {
  const label = serviceType || "Domestic";
  const lower = label.toLowerCase();

  if (lower.includes("communication") || lower.includes("vas")) {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-slate-800">
        <Sparkles className="h-4 w-4 text-primary shrink-0" />
        <span>{label}</span>
      </span>
    );
  }
  if (lower.includes("b2b") || lower.includes("cargo")) {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-slate-800">
        <Boxes className="h-4 w-4 text-amber-600 shrink-0" />
        <span>{label}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-800">
      <Truck className="h-4 w-4 text-emerald-600 shrink-0" />
      <span>{label}</span>
    </span>
  );
}

export default function InvoicesListPage() {
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const showMerchant = capabilities.isStaff;

  const [activeTab, setActiveTab] = useState<NoteTabType>("INVOICE");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const cacheKey = buildQueryCacheKey(
    tenantSlug,
    showMerchant ? "staff" : "customer",
    "invoices",
    { tab: activeTab, search: searchQuery.trim() }
  );
  const [invoices, setInvoices] = useState<BillingInvoiceRead[]>(
    () => getCachedQuery<BillingInvoiceRead[]>(cacheKey) ?? []
  );
  const [loading, setLoading] = useState<boolean>(
    () => getCachedQuery<BillingInvoiceRead[]>(cacheKey) === null
  );
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const columns = NOTE_TAB_COLUMNS[activeTab];

  const fetchInvoices = useCallback(async () => {
    if (!tenantSlug) return;
    const cached = getCachedQuery<BillingInvoiceRead[]>(cacheKey);
    if (cached !== null) {
      setInvoices(cached);
    } else {
      setLoading(true);
    }
    try {
      const searchParam = searchQuery.trim() ? searchQuery.trim() : null;
      const rows = await InvoicesService.listBillingInvoices(
        activeTab === "ALL" ? undefined : activeTab,
        searchParam,
        tenantSlug
      );
      const list = rows || [];
      setCachedQuery(cacheKey, list);
      setInvoices(list);
    } catch (err: unknown) {
      if (cached === null) {
        toast.error(
          extractApiErrorMessage(err, "Failed to load billing invoices.")
        );
      }
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, activeTab, searchQuery, cacheKey]);

  useEffect(() => {
    fetchInvoices();
  }, [fetchInvoices]);

  const filteredInvoices = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const filtered = invoices.filter((inv) => {
      if (!isWithinDateRange(inv.invoice_date, dateFrom, dateTo)) return false;
      if (!q) return true;
      return (
        inv.invoice_number.toLowerCase().includes(q) ||
        (inv.tracking_id || "").toLowerCase().includes(q) ||
        (inv.gst_number || "").toLowerCase().includes(q) ||
        (inv.service_type || "").toLowerCase().includes(q)
      );
    });

    return filtered.slice().sort((a, b) => {
      const tA = new Date(a.invoice_date).getTime();
      const tB = new Date(b.invoice_date).getTime();
      return sortAsc ? tA - tB : tB - tA;
    });
  }, [invoices, searchQuery, sortAsc, dateFrom, dateTo]);

  const handleDownloadPdf = async (inv: BillingInvoiceRead) => {
    const key = ["pdf", inv.invoice_number].join("-");
    setDownloadingKey(key);
    try {
      const url = ["/api/v1/invoices/", inv.invoice_number, "/pdf"].join("");
      const filename = ["invoice_", inv.invoice_number, ".pdf"].join("");
      await downloadInvoiceFileBlob(url, filename);
      toast.success(["Downloaded PDF for ", inv.invoice_number].join(""));
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Unable to download invoice PDF.")
      );
    } finally {
      setDownloadingKey(null);
    }
  };

  const handleDownloadCsv = async (inv: BillingInvoiceRead) => {
    const key = ["csv", inv.invoice_number].join("-");
    setDownloadingKey(key);
    try {
      const url = [
        "/api/v1/invoices/",
        inv.invoice_number,
        "/transactions-csv",
      ].join("");
      const filename = [
        "invoice_",
        inv.invoice_number,
        "_transactions.csv",
      ].join("");
      await downloadInvoiceFileBlob(url, filename);
      toast.success(
        ["Downloaded transaction CSV for ", inv.invoice_number].join("")
      );
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Unable to download transactions CSV.")
      );
    } finally {
      setDownloadingKey(null);
    }
  };

  return (
    <div className="space-y-5 pb-10">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-heading">
            Invoices
          </h1>
          <LearnMore title="Invoices, credit notes & debit notes" points={INVOICES_HELP_POINTS} />
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchInvoices}
            disabled={loading}
            className="h-9 gap-1.5"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", loading && "animate-spin")}
            />
            Refresh
          </Button>
          {/* C-05: no manual "Issue GST Document" in the MVP. Every GST document is
              issued by the booking / re-price / charge flows with its own shipment. */}
        </div>
      </div>

      <div className="border-b border-slate-200">
        <nav className="-mb-px flex space-x-6 overflow-x-auto" aria-label="Tabs">
          {NOTE_TABS.map((tab) => {
            const active = activeTab === tab.value;
            return (
              <button
                key={tab.value}
                type="button"
                data-testid={getTabTestId(tab.value)}
                onClick={() => setActiveTab(tab.value)}
                className={cn(
                  "whitespace-nowrap border-b-2 py-3 px-1 text-sm font-semibold transition-colors",
                  active
                    ? "border-primary text-primary"
                    : "border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900"
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by document ID or AWB"
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
          <span className="text-xs font-medium text-slate-600">Date range</span>
          <Input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="From date"
            className="h-10 w-40 min-w-0 max-w-full bg-white border-slate-200 text-sm"
            data-testid="invoices.filters.from"
          />
          <span className="text-xs text-slate-500">to</span>
          <Input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label="To date"
            className="h-10 w-40 min-w-0 max-w-full bg-white border-slate-200 text-sm"
            data-testid="invoices.filters.to"
          />
          {(dateFrom || dateTo) && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setDateFrom("");
                setDateTo("");
              }}
              className="h-9 px-2.5 text-xs text-slate-600 hover:text-slate-900"
            >
              Reset dates
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
                Loading billing records
              </span>
            </div>
          ) : filteredInvoices.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <div className="h-12 w-12 rounded-full bg-slate-100 flex items-center justify-center mb-3">
                <FileText className="h-6 w-6 text-slate-400" />
              </div>
              <p className="text-base font-semibold text-slate-800">
                No documents found in this tab
              </p>
              <p className="text-xs text-slate-500 mt-1 max-w-md">
                Issued GST invoices, credit notes, and debit notes will appear
                here.
              </p>
            </div>
          ) : (
            <>
              <div className="hidden md:block">
                <Table>
                  <TableHeader className="bg-slate-50">
                    <TableRow className="border-slate-200">
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5 pl-6">
                        {columns.id}
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        <button
                          type="button"
                          onClick={() => setSortAsc((prev) => !prev)}
                          className="inline-flex items-center gap-1 hover:text-slate-800"
                        >
                          {columns.date}
                          <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
                        </button>
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        GST NUMBER
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        SERVICE TYPE
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        {columns.amount}
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5 pr-6 text-right">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredInvoices.map((inv) => {
                      const invAmt = getInvoiceTotalValue(inv);
                      const detailHref = routeTo(
                        ["/finances/invoices/", inv.invoice_number].join("")
                      );
                      const isDownloading =
                        downloadingKey ===
                          ["pdf", inv.invoice_number].join("-") ||
                        downloadingKey ===
                          ["csv", inv.invoice_number].join("-");

                      return (
                        <TableRow
                          key={inv.id}
                          className="border-slate-100 hover:bg-slate-50 transition-colors"
                          data-testid={`invoices.row.${inv.invoice_number}`}
                        >
                          <TableCell className="py-3.5 pl-6 font-medium">
                            <div className="flex flex-col gap-0.5">
                              <div className="flex items-center gap-2">
                                <Link
                                  href={detailHref}
                                  className="text-primary hover:underline font-medium text-sm"
                                >
                                  {inv.invoice_number}
                                </Link>
                                {activeTab === "ALL" && (
                                  <DocumentTypeBadge noteType={inv.note_type} />
                                )}
                              </div>
                              {inv.tracking_id && (
                                <span className="text-[11px] font-mono text-slate-500">
                                  AWB {inv.tracking_id}
                                </span>
                              )}
                              {showMerchant && inv.merchant_email && (
                                <span
                                  className="text-[11px] font-medium text-slate-700"
                                  data-testid={`invoices.row.${inv.invoice_number}.merchant`}
                                >
                                  {inv.merchant_email}
                                </span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="py-3.5 text-sm font-medium text-slate-800">
                            {safeFormatDate(inv.invoice_date, "d MMM, yyyy")}
                          </TableCell>
                          <TableCell className="py-3.5 text-sm text-slate-700 font-mono">
                            {inv.gst_number}
                          </TableCell>
                          <TableCell className="py-3.5">
                            {renderServiceTypeCell(inv.service_type)}
                          </TableCell>
                          <TableCell className="py-3.5 text-sm font-medium text-slate-900">
                            <span data-testid={`invoices.row.${inv.invoice_number}.total`}>₹{formatInrValue(invAmt)}</span>
                          </TableCell>
                          <TableCell className="py-3.5 pr-6 text-right">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <button
                                  type="button"
                                  disabled={isDownloading}
                                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline disabled:opacity-50"
                                >
                                  {isDownloading ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Download className="h-3.5 w-3.5" />
                                  )}
                                  Download
                                  <ChevronDown className="h-3.5 w-3.5" />
                                </button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-56">
                                <DropdownMenuItem
                                  onClick={() => handleDownloadPdf(inv)}
                                  className="cursor-pointer gap-2 text-xs"
                                  data-testid="invoice-detail.actions.download-pdf"
                                >
                                  <FileText className="h-4 w-4 text-slate-600" />
                                  Download Invoice PDF
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onClick={() => handleDownloadCsv(inv)}
                                  className="cursor-pointer gap-2 text-xs"
                                >
                                  <FileSpreadsheet className="h-4 w-4 text-slate-600" />
                                  Download Transaction List CSV
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>

              <div className="md:hidden divide-y divide-slate-100">
                {filteredInvoices.map((inv) => {
                  const invAmt = getInvoiceTotalValue(inv);
                  const detailHref = routeTo(
                    ["/finances/invoices/", inv.invoice_number].join("")
                  );
                  const isOverdue =
                    (inv.status || "").toUpperCase() === "OVERDUE";

                  return (
                    <div key={inv.id} className="p-4 space-y-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <Link
                            href={detailHref}
                            className="text-sm font-semibold text-primary hover:underline"
                          >
                            {inv.invoice_number}
                          </Link>
                          <p className="text-xs text-slate-500 mt-0.5">
                            {safeFormatDate(inv.invoice_date, "d MMM, yyyy")}
                            {inv.tracking_id ? ` · AWB ${inv.tracking_id}` : ""}
                          </p>
                          {showMerchant && inv.merchant_email && (
                            <p className="text-[11px] font-medium text-slate-700 break-all">
                              {inv.merchant_email}
                            </p>
                          )}
                        </div>
                        {inv.is_note ? (
                          <DocumentTypeBadge noteType={inv.note_type} />
                        ) : (
                          <Badge
                            variant="outline"
                            className={cn(
                              "rounded-full px-2.5 py-0.5 text-xs font-medium",
                              isOverdue
                                ? "bg-rose-50 text-rose-700 border-rose-200"
                                : "bg-emerald-50 text-emerald-700 border-emerald-200"
                            )}
                          >
                            {isOverdue ? "Overdue" : "Paid"}
                          </Badge>
                        )}
                      </div>

                      <div className="flex items-center justify-between text-xs text-slate-600">
                        {renderServiceTypeCell(inv.service_type)}
                        <span className="text-sm font-bold text-slate-900">
                          <span data-testid={`invoices.row.${inv.invoice_number}.total`}>₹{formatInrValue(invAmt)}</span>
                        </span>
                      </div>

                      <div className="flex items-center justify-between pt-1 text-xs">
                        <span className="font-mono text-slate-500">
                          GST: {inv.gst_number}
                        </span>
                        <div className="flex items-center gap-3">
                          <button
                            type="button"
                            onClick={() => handleDownloadPdf(inv)}
                            className="font-semibold text-primary hover:underline"
                            data-testid="invoice-detail.actions.download-pdf"
                          >
                            PDF
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadCsv(inv)}
                            className="font-semibold text-primary hover:underline"
                          >
                            CSV
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>

    </div>
  );
}
