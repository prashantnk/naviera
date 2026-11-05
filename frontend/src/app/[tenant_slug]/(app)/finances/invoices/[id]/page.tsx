"use client";

import type {
  BillingInvoiceRead,
} from
  "@/api_client";
import {
  InvoicesService,
} from
  "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { CLAIMS_FINANCE_CHIP } from "@/components/support/ticket-rules";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSingleFlight } from "@/hooks/use-single-flight";
import {
  cn,
  extractApiErrorMessage,
  safeFormatDate,
} from "@/lib/utils";
import {
  AlertCircle,
  ArrowLeft,
  Banknote,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  Headphones,
  Info,
  Loader2,
  Receipt,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

function formatInrAmount(val: number | undefined | null): string {
  const num = Number(val ?? 0);
  return num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getBaseChargeAmount(inv: BillingInvoiceRead): number {
  return Number(inv.freight_amount ?? 0);
}

function getInvoiceGrandSum(inv: BillingInvoiceRead): number {
  return Number(inv.total_amount ?? 0);
}

async function downloadInvoiceBlob(
  endpointUrl: string,
  filename: string
): Promise<void> {
  const { OpenAPI } = await import("@/api_client");
  const axios = (await import("axios")).default;

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

export default function InvoiceDetailPage() {
  const params = useParams();
  const identifier = decodeURIComponent(String(params?.id || ""));
  const { routeTo, tenantSlug } = useTenant();

  const [invoice, setInvoice] = useState<BillingInvoiceRead | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const { pending: downloadingPdf, run: runPdfDownload } = useSingleFlight();
  const { pending: downloadingCsv, run: runCsvDownload } = useSingleFlight();

  const fetchInvoice = useCallback(async () => {
    if (!tenantSlug || !identifier) return;
    setLoading(true);
    try {
      const detail = await InvoicesService.getBillingInvoiceDetail(
        identifier,
        tenantSlug
      );
      setInvoice(detail);
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Unable to load invoice details.")
      );
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, identifier]);

  useEffect(() => {
    fetchInvoice();
  }, [fetchInvoice]);

  const handleDownloadPdf = () => {
    if (!invoice) return;
    void runPdfDownload(async () => {
      try {
        const url = ["/api/v1/invoices/", invoice.invoice_number, "/pdf"].join(
          ""
        );
        const filename = ["invoice_", invoice.invoice_number, ".pdf"].join("");
        await downloadInvoiceBlob(url, filename);
        toast.success(`Downloaded ${invoice.document_title} PDF.`);
      } catch (err: unknown) {
        toast.error(
          extractApiErrorMessage(err, "Failed to download invoice PDF.")
        );
      }
    });
  };

  const handleDownloadTransactionsCsv = () => {
    if (!invoice) return;
    void runCsvDownload(async () => {
      try {
        const url = [
          "/api/v1/invoices/",
          invoice.invoice_number,
          "/transactions-csv",
        ].join("");
        const filename = [
          "invoice_",
          invoice.invoice_number,
          "_transactions.csv",
        ].join("");
        await downloadInvoiceBlob(url, filename);
        toast.success("Downloaded invoice transactions CSV.");
      } catch (err: unknown) {
        toast.error(
          extractApiErrorMessage(err, "Failed to download transactions CSV.")
        );
      }
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-500 gap-2">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span className="text-sm font-medium">
          Loading invoice details
        </span>
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="max-w-3xl mx-auto py-16 text-center space-y-4">
        <p className="text-base font-semibold text-slate-800">
          Invoice not found
        </p>
        <Button asChild variant="outline" size="sm">
          <Link href={routeTo("/finances/invoices")}>
            Back to Invoices
          </Link>
        </Button>
      </div>
    );
  }

  const statusUpper = (invoice.status || "PAID").toUpperCase();
  const isOverdue = statusUpper === "OVERDUE";
  const formattedInvoiceDate = safeFormatDate(
    invoice.invoice_date,
    "d MMM, yyyy"
  );
  const formattedDueDate = safeFormatDate(invoice.due_date, "d MMM, yyyy");
  const baseCharge = getBaseChargeAmount(invoice);
  const grandSum = getInvoiceGrandSum(invoice);
  const billTo = invoice.bill_to;
  const isVas = (invoice.service_type || "").toLowerCase().includes("vas");
  const needHelpHref = invoice.tracking_id
    ? routeTo(
        [
          "/support?awb=",
          encodeURIComponent(invoice.tracking_id),
          "&category=",
          encodeURIComponent(CLAIMS_FINANCE_CHIP),
        ].join("")
      )
    : routeTo("/support");

  return (
    <div className="max-w-6xl space-y-6 pb-12">
      <div className="flex items-center gap-3">
        <Button
          asChild
          variant="outline"
          size="icon"
          className="h-9 w-9 rounded-lg border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
        >
          <Link
            href={routeTo("/finances/invoices")}
            aria-label="Back to Invoices"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <span className="text-sm font-semibold text-slate-800">
          {invoice.document_title} Details
        </span>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white shadow-2xs">
              <FileText className="h-6 w-6 text-slate-700" />
            </div>
            <div>
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 font-heading break-all">
                {invoice.invoice_number}
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">
                {invoice.document_title}
                {" · "}
                {invoice.service_type || "Domestic"}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {!invoice.is_note && (
              <Badge
                variant="outline"
                className={cn(
                  "rounded-full px-3 py-0.5 text-xs font-medium",
                  isOverdue
                    ? "bg-rose-50 text-rose-700 border-rose-200"
                    : "bg-emerald-50 text-emerald-700 border-emerald-200"
                )}
              >
                {isOverdue ? "Overdue" : "Paid"}
              </Badge>
            )}

            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
              <Calendar className="h-3.5 w-3.5 text-slate-500" />
              {invoice.is_note ? "Note Date" : "Invoice Date"}: {formattedInvoiceDate}
            </span>
          </div>
        </div>

        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-9 gap-2 border-slate-200 bg-white text-slate-800 hover:bg-slate-50 self-start"
        >
          <Link href={needHelpHref}>
            <Headphones className="h-4 w-4 text-slate-600" />
            Need Help?
          </Link>
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-7 space-y-4">
          <Card className="border-slate-200 shadow-xs bg-white">
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                  <Receipt className="h-4 w-4" />
                </div>
                <CardTitle className="text-base font-semibold text-slate-900">
                  {invoice.document_title} Details
                </CardTitle>
              </div>

              <button
                type="button"
                onClick={handleDownloadPdf}
                disabled={downloadingPdf}
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline disabled:opacity-50"
              >
                {downloadingPdf ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Download PDF
              </button>
            </CardHeader>

            <CardContent>
              <div className="rounded-xl bg-slate-50 border border-slate-100 p-6 space-y-5">
                <div className="flex items-center justify-center gap-3.5 py-1">
                  <div
                    className={cn(
                      "flex h-11 w-11 items-center justify-center rounded-full",
                      isOverdue
                        ? "bg-amber-100 text-amber-600"
                        : "bg-emerald-100 text-emerald-600"
                    )}
                  >
                    {isOverdue ? (
                      <AlertCircle className="h-6 w-6" />
                    ) : (
                      <CheckCircle2 className="h-6 w-6" />
                    )}
                  </div>
                  <div>
                    <p className="text-xs font-medium text-slate-500">
                      {invoice.is_note ? "Note Amount" : "Invoice Amount"}
                    </p>
                    <p className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
                      ₹ {formatInrAmount(grandSum)}
                    </p>
                  </div>
                </div>

                <div className="border-t border-slate-200" />

                <div
                  className="rounded-lg border border-slate-200 bg-white p-4 space-y-1"
                  data-testid="invoice-detail.bill-to"
                >
                  <p className="text-xs font-semibold text-slate-700">Bill To</p>
                  {billTo?.name && (
                    <p className="text-sm font-semibold text-slate-900">{billTo.name}</p>
                  )}
                  {billTo?.address && (
                    <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
                      {billTo.address}
                    </p>
                  )}
                  <p className="text-xs text-slate-700">
                    <span className="font-semibold">GSTIN: </span>
                    <span className="font-mono" data-testid="invoice-detail.bill-to.gstin">
                      {billTo?.gstin || "Unregistered"}
                    </span>
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-xs font-semibold text-slate-700">
                      Place of Supply
                    </p>
                    <p
                      className="text-sm font-medium text-slate-900 mt-0.5"
                      data-testid="invoice-detail.place-of-supply"
                    >
                      {invoice.place_of_supply_label || "-"}
                    </p>
                  </div>

                  {invoice.is_note ? (
                    <div>
                      <p className="text-xs font-semibold text-slate-700">
                        Against Invoice
                      </p>
                      <p
                        className="text-sm font-medium text-slate-900 mt-0.5"
                        data-testid="invoice-detail.original-invoice"
                      >
                        {invoice.original_invoice_number || "-"}
                        {invoice.original_invoice_date && (
                          <span className="text-xs text-slate-500">
                            {" (dated "}
                            {safeFormatDate(invoice.original_invoice_date, "d MMM, yyyy")}
                            {")"}
                          </span>
                        )}
                      </p>
                    </div>
                  ) : (
                    <div>
                      <p className="text-xs font-semibold text-slate-700">
                        Due Date
                      </p>
                      <p className="text-sm font-medium text-slate-900 mt-0.5">
                        {formattedDueDate}
                      </p>
                    </div>
                  )}

                  {invoice.tracking_id && (
                    <div>
                      <p className="text-xs font-semibold text-slate-700">AWB</p>
                      <p className="text-sm font-mono font-medium text-slate-900 mt-0.5">
                        {invoice.tracking_id}
                      </p>
                    </div>
                  )}

                  <div>
                    <p className="text-xs font-semibold text-slate-700">
                      Reverse Charge
                    </p>
                    <p className="text-sm font-medium text-slate-900 mt-0.5">No</p>
                  </div>
                </div>

                <div className="border-t border-slate-200 pt-4 space-y-1">
                  <p className="text-xs font-semibold text-slate-700">
                    Supplier
                  </p>
                  {invoice.supplier_name && (
                    <p className="text-sm font-semibold text-slate-900">
                      {invoice.supplier_name}
                    </p>
                  )}
                  <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
                    {invoice.billing_address}
                  </p>
                  <p className="text-xs text-slate-700">
                    <span className="font-semibold">GSTIN: </span>
                    <span className="font-mono">{invoice.gst_number}</span>
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-primary/20 bg-primary/5 px-5 py-4">
            <div className="flex items-center gap-2.5 text-sm font-semibold text-primary">
              <Info className="h-4 w-4 shrink-0" />
              <span>View invoice charges by transaction</span>
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={handleDownloadTransactionsCsv}
              disabled={downloadingCsv}
              className="h-9 bg-white border-slate-200 text-slate-800 hover:bg-slate-50 text-xs font-semibold gap-1 self-start sm:self-auto"
            >
              {downloadingCsv && (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              )}
              Download Transaction list
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <div className="lg:col-span-5 space-y-4">
          <Card className="border-slate-200 shadow-xs bg-white">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                  <Banknote className="h-4 w-4" />
                </div>
                <CardTitle className="text-base font-semibold text-slate-900">
                  Bill Info
                </CardTitle>
              </div>
            </CardHeader>

            <CardContent className="space-y-4 text-sm">
              <div className="flex items-center justify-between text-slate-700">
                <span className="font-medium">
                  {isVas ? (
                    "VAS charges"
                  ) : (
                    <>
                      <span>
                        Freight
                      </span>
                      <span>{" / "}</span>
                      <span>VAS Charges</span>
                    </>
                  )}
                </span>
                <span className="font-semibold text-slate-900">
                  ₹ {formatInrAmount(baseCharge)}
                </span>
              </div>

              {invoice.tax_rows.map((row) => (
                <div
                  key={row.label}
                  className="flex items-center justify-between text-slate-700"
                  data-testid="invoice-detail.tax-row"
                >
                  <span className="font-medium">{row.label}</span>
                  <span className="font-medium text-slate-800">
                    + ₹ {formatInrAmount(row.amount)}
                  </span>
                </div>
              ))}

              <div className="border-t border-slate-200 pt-3.5 flex items-center justify-between">
                <span className="font-semibold text-slate-900">
                  <span>
                    Total Amount
                  </span>
                </span>
                <span className="text-base font-bold text-slate-900">
                  ₹ {formatInrAmount(grandSum)}
                </span>
              </div>
            </CardContent>
          </Card>

          <div className="px-2 space-y-1.5 text-xs text-slate-600">
            <p className="font-semibold text-slate-800 flex items-center gap-1.5">
              <Info className="h-3.5 w-3.5 text-slate-500" />
              Additional Charges
            </p>
            <ul className="list-disc pl-5 space-y-1 text-[11px] text-slate-600">
              <li>
                No Additional txn charges for netbanking on Current accounts
              </li>
              <li>
                Additional transaction charges may apply on Credit or Debit
                cards and netbanking on Savings account
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
