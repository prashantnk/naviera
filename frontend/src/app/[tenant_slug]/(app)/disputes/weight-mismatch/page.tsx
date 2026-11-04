"use client";

import type {
  WeightDisputeClaimCreate,
  WeightDisputeRead,
  WeightDisputeResolveRequest,
} from
  "@/api_client";
import {
  DisputesService,
} from
  "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { LearnMore } from "@/components/finance/learn-more";
import {
  CLAIM_STATUS,
  WEIGHT_CLAIM_HELP_CATEGORY,
  claimBlockReason,
  claimStatusLabel,
  claimStatusOf,
  firstClaimableRow,
} from "@/components/finance/weight-claim";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useSignedDocumentUrl } from "@/lib/document-storage";
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
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  ArrowUpDown,
  Box,
  CheckCircle2,
  Download,
  Eye,
  Info,
  ListChecks,
  Loader2,
  Package,
  Plus,
  Scale,
  Search,
  ShoppingBag,
  Table2,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

type DisputePageMode = "list" | "create";

const EXPORT_API_PREFIX = "/api/v1/disputes/";
const EXPORT_API_SLUG = "weight-mismatch";
const EXPORT_API_SUFFIX = "/export/csv";

/** Plain-language rules behind the "Learn More" pill (Delhivery One help slug `weight-dispute`). */
const WEIGHT_MISMATCH_HELP_POINTS: readonly string[] = [
  "You are billed on the higher of dead weight and volumetric weight (L x B x H / 5000). When our hub weighs a parcel heavier than you declared, the extra freight is debited from your wallet and the AWB appears here.",
  "Raise a claim (one AWB at a time) with the weight you believe is right and any packing evidence. The claim stays under review until our team decides.",
  "If the claim is accepted, the difference is refunded to your wallet with a credit note. If it is rejected, use Need help? to raise a support ticket.",
  "Avoid mismatches: enter the packed weight and box size, and use a box that fits the product.",
];

/** Badge colours per claim status. */
const CLAIM_BADGE_CLASSES: Record<string, string> = {
  [CLAIM_STATUS.ACCEPTED]: "bg-emerald-50 text-emerald-700 border-emerald-200",
  [CLAIM_STATUS.REJECTED]: "bg-rose-50 text-rose-700 border-rose-200",
  [CLAIM_STATUS.CLAIM_RAISED]: "bg-amber-50 text-amber-700 border-amber-200",
};

interface ClaimStatusBadgeProps {
  row: WeightDisputeRead;
  viewerIsStaff: boolean;
  /** `/support` deep link that pre-fills a ticket for this AWB (shown on rejected claims). */
  needHelpHref: string;
}

/**
 * Claim state of one AWB: a readable badge, the team's decision remarks once the
 * claim is closed, and Delhivery One's "Need help?" link on a rejected claim.
 */
function ClaimStatusBadge({ row, viewerIsStaff, needHelpHref }: ClaimStatusBadgeProps) {
  const status = claimStatusOf(row);
  const isClosed = status === CLAIM_STATUS.ACCEPTED || status === CLAIM_STATUS.REJECTED;
  return (
    <div className="flex flex-col items-end gap-1 text-right">
      <Badge
        variant="outline"
        className={cn(
          "rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
          CLAIM_BADGE_CLASSES[status]
        )}
        data-testid={`weight-mismatch.row.${row.tracking_id}.claim-status`}
      >
        {claimStatusLabel(status, viewerIsStaff)}
      </Badge>
      {isClosed && row.claim_remarks && (
        <span className="max-w-[220px] text-[11px] text-slate-500 line-clamp-2">
          {row.claim_remarks}
        </span>
      )}
      {status === CLAIM_STATUS.REJECTED && !viewerIsStaff && (
        <Link
          href={needHelpHref}
          className="text-[11px] font-semibold text-primary hover:underline"
          data-testid={`weight-mismatch.row.${row.tracking_id}.need-help`}
        >
          Need help?
        </Link>
      )}
    </div>
  );
}

function formatInrNumber(val: number | undefined | null): string {
  const num = Number(val ?? 0);
  return num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getManifestedGrams(row: WeightDisputeRead): number {
  return Number(row.manifested_weight_g ?? 0);
}

function getChargedGrams(row: WeightDisputeRead): number {
  return Number(row.charged_weight_g ?? 0);
}

function getClaimedGrams(row: WeightDisputeRead): number | null {
  if (row.claimed_weight_g === undefined || row.claimed_weight_g === null) {
    return null;
  }
  return Number(row.claimed_weight_g);
}

function getCostDiffInr(row: WeightDisputeRead): number {
  return Number(row.cost_diff_inr ?? 0);
}

function getShippingCostInr(row: WeightDisputeRead): number {
  return Number(row.shipping_cost_inr ?? 0);
}

function getShipmentValueInr(row: WeightDisputeRead): number {
  return Number(row.shipment_value_inr ?? 0);
}

async function downloadMismatchCsvBlob(searchQuery: string): Promise<void> {
  const { OpenAPI } = await import("@/api_client");
  const axios = (await import("axios")).default;
  const endpointUrl = [
    EXPORT_API_PREFIX,
    EXPORT_API_SLUG,
    EXPORT_API_SUFFIX,
  ].join("");

  const headers =
    typeof OpenAPI.HEADERS === "function"
      ? await OpenAPI.HEADERS({
          method: "GET",
          url: endpointUrl,
        })
      : OpenAPI.HEADERS || {};

  const params: Record<string, string> = {};
  if (searchQuery.trim()) {
    params.search = searchQuery.trim();
  }

  const response = await axios.get(endpointUrl, {
    headers,
    params,
    responseType: "blob",
  });

  const blob = new Blob([response.data], {
    type: String(response.headers["content-type"] || "text/csv"),
  });
  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  const csvName = ["disputes_", EXPORT_API_SLUG, ".csv"].join("");
  anchor.download = csvName;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(downloadUrl);
  document.body.removeChild(anchor);
}

export default function WeightMismatchDisputesPage() {
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const canRaiseClaims = capabilities.canWrite;
  const canResolveClaims = capabilities.canManageFinance;
  const viewerIsStaff = capabilities.isStaff;
  const needHelpHref = (awb: string) =>
    routeTo(
      [
        "/support?awb=",
        encodeURIComponent(awb),
        "&category=",
        encodeURIComponent(WEIGHT_CLAIM_HELP_CATEGORY),
      ].join("")
    );

  const [viewMode, setViewMode] = useState<DisputePageMode>("list");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const cacheKey = buildQueryCacheKey(
    tenantSlug,
    viewerIsStaff ? "staff" : "customer",
    "weight-mismatch",
    { search: searchQuery.trim() }
  );
  const [disputes, setDisputes] = useState<WeightDisputeRead[]>(
    () => getCachedQuery<WeightDisputeRead[]>(cacheKey) ?? []
  );
  const [loading, setLoading] = useState<boolean>(
    () => getCachedQuery<WeightDisputeRead[]>(cacheKey) === null
  );
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [downloadingCsv, setDownloadingCsv] = useState<boolean>(false);

  const [sorterPreviewRow, setSorterPreviewRow] =
    useState<WeightDisputeRead | null>(null);
  const sorterImageSrc = useSignedDocumentUrl(tenantSlug, sorterPreviewRow?.sorter_image_url);

  const [selectedAwbs, setSelectedAwbs] = useState<string[]>([]);
  const [awbInputText, setAwbInputText] = useState<string>("");
  const [showClaimInput, setShowClaimInput] = useState<boolean>(false);
  const [claimedGramsInput, setClaimedGramsInput] = useState<string>("");
  const [claimRemarksInput, setClaimRemarksInput] = useState<string>("");
  const [submittingClaim, setSubmittingClaim] = useState<boolean>(false);

  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveTarget, setResolveTarget] = useState<{
    row: WeightDisputeRead;
    decision: "ACCEPTED" | "REJECTED";
  } | null>(null);
  const [adminResolveRemarks, setAdminResolveRemarks] = useState<string>("");

  const fetchDisputes = useCallback(async () => {
    if (!tenantSlug) return;
    const cached = getCachedQuery<WeightDisputeRead[]>(cacheKey);
    if (cached !== null) {
      setDisputes(cached);
    } else {
      setLoading(true);
    }
    try {
      const searchParam = searchQuery.trim() ? searchQuery.trim() : null;
      const rows = await DisputesService.listWeightMismatchDisputes(
        searchParam,
        null,
        tenantSlug
      );
      const list = rows || [];
      setCachedQuery(cacheKey, list);
      setDisputes(list);
    } catch (err: unknown) {
      if (cached === null) {
        toast.error(
          extractApiErrorMessage(err, "Failed to load mismatch disputes.")
        );
      }
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, searchQuery, cacheKey]);

  useEffect(() => {
    fetchDisputes();
  }, [fetchDisputes]);

  const filteredDisputes = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const list = disputes.filter((d) => {
      if (!q) return true;
      return (
        d.tracking_id.toLowerCase().includes(q) ||
        (d.order_reference_id || "").toLowerCase().includes(q)
      );
    });

    return list.slice().sort((a, b) => {
      const tA = new Date(a.raised_at).getTime();
      const tB = new Date(b.raised_at).getTime();
      return sortAsc ? tA - tB : tB - tA;
    });
  }, [disputes, searchQuery, sortAsc]);

  const selectedShipmentRows = useMemo<WeightDisputeRead[]>(() => {
    return selectedAwbs
      .map((awb) =>
        disputes.find((d) => d.tracking_id.toLowerCase() === awb.toLowerCase())
      )
      .filter((row): row is WeightDisputeRead => Boolean(row));
  }, [selectedAwbs, disputes]);

  const handleOpenCreateClaimForRow = (row: WeightDisputeRead) => {
    setSelectedAwbs([row.tracking_id]);
    const manifestVal = getManifestedGrams(row);
    setClaimedGramsInput(String(manifestVal));
    setClaimRemarksInput(row.claim_remarks || "");
    setShowClaimInput(true);
    setViewMode("create");
  };

  const handleOpenNewClaimBlank = () => {
    const firstRow = firstClaimableRow(filteredDisputes);
    if (firstRow) {
      setSelectedAwbs([firstRow.tracking_id]);
      setClaimedGramsInput(String(getManifestedGrams(firstRow)));
      setClaimRemarksInput("");
    } else {
      setSelectedAwbs([]);
      setClaimedGramsInput("");
    }
    setShowClaimInput(true);
    setViewMode("create");
  };

  const handleSelectSingleAwb = (rawAwb: string) => {
    const cleaned = rawAwb.trim().replace(/,/g, "");
    if (!cleaned) return;
    const matched = disputes.find(
      (d) => d.tracking_id.toLowerCase() === cleaned.toLowerCase()
    );
    const blockReason = claimBlockReason(matched, cleaned);
    if (!matched || blockReason) {
      toast.error(blockReason);
      return;
    }
    setSelectedAwbs([matched.tracking_id]);
    setClaimedGramsInput(String(getManifestedGrams(matched)));
    setAwbInputText("");
  };

  const handleAddAwbChip = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      handleSelectSingleAwb(awbInputText);
    }
  };

  const handleAddAwbButton = () => {
    handleSelectSingleAwb(awbInputText);
  };

  const handleRemoveAwbChip = (awb: string) => {
    setSelectedAwbs((prev) => prev.filter((item) => item !== awb));
  };

  const handleSubmitClaims = async () => {
    const targetIds =
      selectedAwbs.length > 0
        ? selectedAwbs
        : awbInputText.trim()
        ? [awbInputText.trim()]
        : [];
    if (targetIds.length === 0) {
      toast.error("Please select an audited AWB number.");
      return;
    }
    if (targetIds.length > 1) {
      toast.error(
        "Bulk weight claims are disabled. Please raise a claim for one AWB at a time."
      );
      return;
    }

    const parsedGrams = claimedGramsInput.trim()
      ? Number(claimedGramsInput.trim())
      : null;
    if (parsedGrams === null || Number.isNaN(parsedGrams) || parsedGrams <= 0) {
      toast.error("Enter a claimed weight greater than 0 g.");
      return;
    }
    const targetRow = selectedShipmentRows[0];
    const chargedGrams = targetRow ? getChargedGrams(targetRow) : 0;
    const manifestedGrams = targetRow ? getManifestedGrams(targetRow) : 0;
    const isFeeOnlyDispute =
      targetRow !== undefined &&
      chargedGrams <= manifestedGrams &&
      getCostDiffInr(targetRow) > 0;
    if (
      targetRow &&
      (isFeeOnlyDispute ? parsedGrams > chargedGrams : parsedGrams >= chargedGrams)
    ) {
      toast.error(
        `Claimed weight (${parsedGrams} g) must be strictly less than the charged weight (${chargedGrams} g).`
      );
      return;
    }

    setSubmittingClaim(true);
    try {
      const payload: WeightDisputeClaimCreate = {
        tracking_ids: targetIds,
        claimed_weight_g: parsedGrams,
        claim_remarks:
          claimRemarksInput.trim() ||
          "Weight discrepancy claim raised by seller",
      };

      await DisputesService.raiseWeightMismatchClaims(payload, tenantSlug);
      toast.success(
        ["Submitted claim for AWB ", targetIds[0], "."].join("")
      );
      setViewMode("list");
      await fetchDisputes();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to submit claim."));
    } finally {
      setSubmittingClaim(false);
    }
  };

  const handleOpenAdminResolve = (
    row: WeightDisputeRead,
    decision: "ACCEPTED" | "REJECTED"
  ) => {
    setResolveTarget({ row, decision });
    setAdminResolveRemarks("");
  };

  const handleConfirmAdminResolve = async () => {
    if (!resolveTarget) return;
    const { row, decision } = resolveTarget;
    setResolvingId(row.id);
    try {
      const expectedClaimed =
        getClaimedGrams(row) ?? getManifestedGrams(row);
      const payload: WeightDisputeResolveRequest & {
        expected_claimed_weight_g?: number;
      } = {
        claim_status: decision,
        claim_remarks:
          adminResolveRemarks.trim() ||
          (decision === "ACCEPTED"
            ? "Claim accepted after weight verification"
            : "Claim rejected after weight verification"),
        expected_claimed_weight_g: expectedClaimed,
      };
      await DisputesService.resolveWeightMismatchDispute(
        row.id,
        payload,
        tenantSlug
      );
      toast.success(
        [
          "Claim for AWB ",
          row.tracking_id,
          " marked as ",
          decision,
          ".",
        ].join("")
      );
      setResolveTarget(null);
      await fetchDisputes();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Unable to resolve claim."));
    } finally {
      setResolvingId(null);
    }
  };

  const handleExportCsv = async () => {
    setDownloadingCsv(true);
    try {
      await downloadMismatchCsvBlob(searchQuery);
      toast.success("Downloaded mismatch disputes CSV.");
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to export CSV."));
    } finally {
      setDownloadingCsv(false);
    }
  };

  if (viewMode === "create") {
    const claimCount = selectedAwbs.length;

    return (
      <div className="max-w-5xl space-y-6 pb-12">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => setViewMode("list")}
            className="h-9 w-9 rounded-lg border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
            aria-label="Back to list"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-lg font-bold text-slate-900 font-heading">
            Create New Claim
          </h1>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          <div className="min-w-0 lg:col-span-8 space-y-5">
            <Card className="min-w-0 overflow-hidden border-slate-200 shadow-xs bg-white">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                    <Table2 className="h-4 w-4" />
                  </div>
                  <CardTitle className="text-base font-semibold text-slate-900">
                    Claim Details
                  </CardTitle>
                </div>
              </CardHeader>

              <CardContent className="min-w-0 space-y-5">
                <div className="min-w-0 space-y-2">
                  <Label className="text-xs font-semibold text-slate-700">
                    AWB Number
                  </Label>
                  <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 focus-within:ring-2 focus-within:ring-primary/20">
                    <Search className="h-4 w-4 text-slate-400 shrink-0" />
                    {selectedAwbs.map((awb) => (
                      <span
                        key={awb}
                        className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-800"
                      >
                        {awb}
                        <button
                          type="button"
                          onClick={() => handleRemoveAwbChip(awb)}
                          className="text-slate-500 hover:text-slate-900"
                          aria-label={["Remove", awb].join(" ")}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    <input
                      type="text"
                      value={awbInputText}
                      onChange={(e) => setAwbInputText(e.target.value)}
                      onKeyDown={handleAddAwbChip}
                      placeholder={
                        selectedAwbs.length === 0
                          ? "Enter AWB number and press Enter"
                          : "Enter a different AWB to replace selection (one AWB per claim)"
                      }
                      className="flex-1 min-w-0 text-xs outline-none bg-transparent text-slate-800 placeholder:text-slate-400"
                    />
                    {awbInputText.trim() && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={handleAddAwbButton}
                        className="h-6 px-2 text-xs text-primary"
                      >
                        Add
                      </Button>
                    )}
                  </div>
                </div>

                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-2xs bg-white">
                  <CardHeader className="pb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                        <Package className="h-4 w-4" />
                      </div>
                      <CardTitle className="text-base font-semibold text-slate-900">
                        List of Shipments
                      </CardTitle>
                    </div>
                  </CardHeader>

                  <CardContent className="space-y-4">
                    {selectedShipmentRows.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-xs text-slate-500">
                        Select or enter an AWB number above to inspect shipment
                        metrics and submit a claim.
                      </div>
                    ) : (
                      selectedShipmentRows.map((row, rowIndex) => {
                        const manifestVal = getManifestedGrams(row);
                        const chargedVal = getChargedGrams(row);
                        const shipCost = getShippingCostInr(row);
                        const shipVal = getShipmentValueInr(row);

                        return (
                          <div
                            key={row.tracking_id}
                            className="rounded-xl border border-slate-200 p-4 space-y-4"
                          >
                            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                              <div className="space-y-2">
                                <div>
                                  <p className="text-xs font-bold uppercase tracking-wide text-slate-900">
                                    {row.order_reference_id || "—"}
                                  </p>
                                  <p className="text-xs text-slate-600 mt-0.5">
                                    AWB# {row.tracking_id}
                                  </p>
                                </div>

                                <div className="inline-flex items-center justify-between gap-6 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-800">
                                  <span className="inline-flex items-center gap-1.5">
                                    <ShoppingBag className="h-3.5 w-3.5 text-slate-500" />
                                    <span>
                                      Weight
                                    </span>
                                  </span>
                                </div>
                              </div>

                              <div className="text-xs text-slate-600 sm:text-right space-y-1">
                                <p>
                                  Weight audited on{" "}
                                  <strong className="text-slate-900">
                                    {safeFormatDate(
                                      row.raised_at,
                                      "d MMM, yyyy"
                                    )}
                                  </strong>
                                </p>
                                <p>
                                  Shipping Cost{" "}
                                  <strong className="text-slate-900">
                                    ₹ {formatInrNumber(shipCost)}
                                  </strong>
                                </p>
                                <p>
                                  Shipment Value{" "}
                                  <strong className="text-slate-900">
                                    ₹ {formatInrNumber(shipVal)}
                                  </strong>
                                </p>
                              </div>
                            </div>

                            <div className="border-t border-slate-100 pt-3 space-y-2.5">
                              <p className="text-xs font-semibold text-slate-800">
                                <span>
                                  Weight
                                </span>
                              </p>

                              <div className="flex flex-wrap items-center gap-4 text-xs">
                                <div>
                                  <p className="text-[11px] text-slate-500">
                                    Manifested
                                  </p>
                                  <p className="text-sm font-semibold text-slate-500 mt-0.5">
                                    {manifestVal} gm
                                  </p>
                                  <p className="text-[11px] text-slate-500">
                                    {row.manifested_dims || "Dimensions not recorded"}
                                  </p>
                                </div>

                                <ArrowRight className="h-4 w-4 text-slate-400 shrink-0" />

                                <div>
                                  <p className="text-[11px] text-slate-500">
                                    Charged
                                  </p>
                                  <p className="text-sm font-bold text-slate-900 mt-0.5">
                                    {chargedVal} gm
                                  </p>
                                  <p className="text-[11px] text-slate-600">
                                    {row.charged_dims || "Dimensions not recorded"}
                                  </p>
                                </div>

                                <ArrowRight className="h-4 w-4 text-slate-400 shrink-0" />

                                <div>
                                  <p className="text-[11px] text-slate-500 mb-1">
                                    Your Claim
                                  </p>
                                  {!showClaimInput ? (
                                    <button
                                      type="button"
                                      onClick={() => setShowClaimInput(true)}
                                      className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary hover:bg-primary/15"
                                    >
                                      <span>{"+ "}</span>
                                      <span>
                                        Add Weight
                                      </span>
                                    </button>
                                  ) : (
                                    <div className="flex items-center gap-1.5">
                                      <Input
                                        type="number"
                                        min="1"
                                        value={claimedGramsInput}
                                        onChange={(e) =>
                                          setClaimedGramsInput(e.target.value)
                                        }
                                        className="h-8 w-28 text-xs"
                                        placeholder="Grams (g)"
                                        data-testid={
                                          rowIndex === 0
                                            ? "weight-mismatch.claim.weight"
                                            : undefined
                                        }
                                      />
                                      <span className="text-xs text-slate-600">
                                        gm
                                      </span>
                                    </div>
                                  )}
                                </div>
                              </div>

                              {showClaimInput && (
                                <div className="pt-2 space-y-1.5">
                                  <Label className="text-xs text-slate-600">
                                    Dispute Remarks (Optional)
                                  </Label>
                                  <Textarea
                                    rows={2}
                                    value={claimRemarksInput}
                                    onChange={(e) =>
                                      setClaimRemarksInput(e.target.value)
                                    }
                                    placeholder="Provide packaging dimension or scale evidence notes"
                                    className="text-xs"
                                    data-testid={
                                      rowIndex === 0
                                        ? "weight-mismatch.claim.remarks"
                                        : undefined
                                    }
                                  />
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}

                    <div className="flex items-center justify-end gap-2 pt-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setViewMode("list")}
                        disabled={submittingClaim}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        onClick={handleSubmitClaims}
                        disabled={submittingClaim || selectedAwbs.length === 0}
                        className="bg-primary text-primary-foreground hover:bg-primary/90"
                        data-testid="weight-mismatch.claim.submit"
                      >
                        {submittingClaim && (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        )}
                        Submit Claim
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </CardContent>
            </Card>
          </div>

          <div className="min-w-0 lg:col-span-4">
            <Card className="min-w-0 overflow-hidden border-slate-200 shadow-xs bg-white">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                    <ListChecks className="h-4 w-4" />
                  </div>
                  <CardTitle className="text-base font-semibold text-slate-900">
                    Summary
                  </CardTitle>
                </div>
              </CardHeader>

              <CardContent className="space-y-3.5 text-xs">
                <div className="flex items-center justify-between text-slate-700">
                  <span className="font-medium">
                    <span>
                      Weight Mismatch
                    </span>
                  </span>
                  <span className="font-bold text-slate-900">
                    {claimCount}
                  </span>
                </div>

                <div className="border-t border-slate-200 pt-3 flex items-center justify-between text-slate-900">
                  <span className="font-semibold">
                    <span>
                      Total No. of Claims
                    </span>
                  </span>
                  <span className="text-sm font-bold">{claimCount}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-10">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-heading">
            <span>
              Weight Mismatch
            </span>
          </h1>
          <LearnMore title="Weight mismatch & claims" points={WEIGHT_MISMATCH_HELP_POINTS} />
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleExportCsv}
            disabled={downloadingCsv}
            className="h-9 gap-1.5 bg-white border-slate-200 text-slate-800 hover:bg-slate-50"
          >
            {downloadingCsv ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Download CSV
          </Button>

          {canRaiseClaims && (
            <Button
              type="button"
              size="sm"
              onClick={handleOpenNewClaimBlank}
              className="h-9 gap-1.5 bg-slate-900 text-white hover:bg-slate-800"
              data-testid="weight-mismatch.actions.new-claim"
            >
              <Plus className="h-4 w-4" />
              New Claim
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
            placeholder="Search by AWB or order ID"
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
      </div>

      <div className="flex items-center gap-2.5 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-xs font-semibold text-primary">
        <Info className="h-4 w-4 shrink-0" />
        <p>
          <span>
            Weight mismatches for
          </span>
          <span>{" RTO/DTO "}</span>
          <span>shipments will be available soon</span>
        </p>
      </div>

      <Card className="border-slate-200 shadow-xs overflow-hidden bg-white">
        <CardContent className="p-0">
          {loading && disputes.length === 0 ? (
            <div
              data-testid="weight-mismatch-loading-skeleton"
              className="space-y-2.5 p-6"
            >
              {[0, 1, 2].map((idx) => (
                <div
                  key={idx}
                  className="h-10 w-full rounded-lg bg-slate-100 animate-pulse"
                />
              ))}
            </div>
          ) : filteredDisputes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <div className="h-12 w-12 rounded-full bg-slate-100 flex items-center justify-center mb-3">
                <Scale className="h-6 w-6 text-slate-400" />
              </div>
              <p className="text-base font-semibold text-slate-800">
                No mismatch records found
              </p>
              <p className="text-xs text-slate-500 mt-1 max-w-md">
                Automated DWS sorter dimension and scale discrepancies will be
                listed here.
              </p>
            </div>
          ) : (
            <>
              <div className="hidden md:block">
                <Table>
                  <TableHeader className="bg-slate-50">
                    <TableRow className="border-slate-200">
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5 pl-5">
                        AWB
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        <button
                          type="button"
                          onClick={() => setSortAsc((prev) => !prev)}
                          className="inline-flex items-center gap-1 hover:text-slate-800"
                        >
                          RAISED ON
                          <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
                        </button>
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        STATUS
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        <span>
                          MANIFESTED WEIGHT
                        </span>
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        <span>
                          CHARGED WEIGHT
                        </span>
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        COST DIFF.
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5">
                        SORTER IMAGES
                      </TableHead>
                      <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 py-3.5 pr-5 text-right">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredDisputes.map((row) => {
                      const manifestG = getManifestedGrams(row);
                      const chargedG = getChargedGrams(row);
                      const costDiff = getCostDiffInr(row);
                      const isDelivered =
                        (row.shipment_status || "Delivered").toLowerCase() ===
                        "delivered";
                      const claimStatusUpper = claimStatusOf(row);
                      const trackHref = row.shipment_id
                        ? routeTo(["/shipments/", row.shipment_id].join(""))
                        : routeTo(["/track/", row.tracking_id].join(""));

                      return (
                        <TableRow
                          key={row.id}
                          data-testid={`weight-mismatch.row.${row.tracking_id}`}
                          className="border-slate-100 hover:bg-slate-50 transition-colors"
                        >
                          <TableCell className="py-3.5 pl-5">
                            <div className="flex items-center gap-2.5">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-700 text-white">
                                <Box className="h-4 w-4" />
                              </div>
                              <div>
                                <Link
                                  href={trackHref}
                                  className="text-xs font-semibold text-primary hover:underline"
                                >
                                  {row.tracking_id}
                                </Link>
                                {row.order_reference_id && (
                                  <p className="text-[11px] text-slate-500">
                                    {row.order_reference_id}
                                  </p>
                                )}
                                {viewerIsStaff && row.merchant_email && (
                                  <p
                                    className="text-[11px] font-medium text-slate-700"
                                    data-testid={`weight-mismatch.row.${row.tracking_id}.merchant`}
                                  >
                                    {row.merchant_email}
                                  </p>
                                )}
                              </div>
                            </div>
                          </TableCell>

                          <TableCell className="py-3.5 text-xs">
                            <p className="font-semibold text-slate-800">
                              {safeFormatDate(row.raised_at, "d MMM, yyyy")}
                            </p>
                            <p className="text-[11px] text-slate-500">
                              {safeFormatDate(row.raised_at, "hh:mm a")}
                            </p>
                          </TableCell>

                          <TableCell className="py-3.5">
                            <Badge
                              variant="outline"
                              className={cn(
                                "rounded-full px-2.5 py-0.5 text-[11px] font-medium",
                                isDelivered
                                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                  : "bg-sky-50 text-sky-700 border-sky-200"
                              )}
                            >
                              {row.shipment_status || "Delivered"}
                            </Badge>
                          </TableCell>

                          <TableCell className="py-3.5 text-xs">
                            <div className="flex items-center justify-between pr-4">
                              <div>
                                <p className="font-bold text-slate-900">
                                  {manifestG} g
                                </p>
                                <p className="text-[11px] text-slate-500">
                                  {row.manifested_dims || "Dimensions not recorded"}
                                </p>
                              </div>
                            </div>
                          </TableCell>

                          <TableCell className="py-3.5 text-xs">
                            <div className="flex items-center justify-between pr-4">
                              <div>
                                <p className="font-bold text-slate-900">
                                  {chargedG} g
                                </p>
                                <p className="text-[11px] text-slate-500 italic">
                                  {row.charged_dims || "Dimensions not recorded"}
                                </p>
                              </div>
                            </div>
                          </TableCell>

                          <TableCell className="py-3.5 text-xs font-semibold italic text-rose-600">
                            <span
                              data-testid={`weight-mismatch.row.${row.tracking_id}.cost-diff`}
                            >
                              ₹{formatInrNumber(costDiff)}
                            </span>
                          </TableCell>

                          <TableCell className="py-3.5">
                            <button
                              type="button"
                              onClick={() => setSorterPreviewRow(row)}
                              className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
                            >
                              <Eye className="h-3.5 w-3.5 text-slate-500" />
                              View Image
                            </button>
                          </TableCell>

                          <TableCell className="py-3.5 pr-5 text-right">
                            <div className="flex items-center justify-end gap-2">
                              {claimStatusUpper === CLAIM_STATUS.NONE ? (
                                canRaiseClaims ? (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleOpenCreateClaimForRow(row)
                                    }
                                    data-testid={`weight-mismatch.row.${row.tracking_id}.raise-claim`}
                                    className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
                                  >
                                    <AlertCircle className="h-3.5 w-3.5 text-slate-600" />
                                    Raise Claim
                                  </button>
                                ) : (
                                  <span className="text-[11px] text-slate-500">
                                    {claimStatusLabel(claimStatusUpper, viewerIsStaff)}
                                  </span>
                                )
                              ) : (
                                <ClaimStatusBadge
                                  row={row}
                                  viewerIsStaff={viewerIsStaff}
                                  needHelpHref={needHelpHref(row.tracking_id)}
                                />
                              )}

                              {canResolveClaims &&
                                claimStatusUpper === CLAIM_STATUS.CLAIM_RAISED && (
                                  <div className="flex items-center gap-1">
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      disabled={resolvingId === row.id}
                                      onClick={() =>
                                        handleOpenAdminResolve(row, "ACCEPTED")
                                      }
                                      className="h-7 px-2 text-[11px] border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                                    >
                                      <CheckCircle2 className="h-3 w-3 mr-1" />
                                      Accept
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      disabled={resolvingId === row.id}
                                      onClick={() =>
                                        handleOpenAdminResolve(row, "REJECTED")
                                      }
                                      className="h-7 px-2 text-[11px] border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
                                    >
                                      <XCircle className="h-3 w-3 mr-1" />
                                      Reject
                                    </Button>
                                  </div>
                                )}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>

              <div className="md:hidden divide-y divide-slate-100">
                {filteredDisputes.map((row) => {
                  const manifestG = getManifestedGrams(row);
                  const chargedG = getChargedGrams(row);
                  const costDiff = getCostDiffInr(row);
                  const claimStatusUpper = claimStatusOf(row);

                  return (
                    <div key={row.id} className="p-4 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <Link
                            href={
                              row.shipment_id
                                ? routeTo(["/shipments/", row.shipment_id].join(""))
                                : routeTo(["/track/", row.tracking_id].join(""))
                            }
                            className="text-sm font-semibold text-primary hover:underline break-all"
                          >
                            {row.tracking_id}
                          </Link>
                          <p className="text-xs text-slate-500">
                            {safeFormatDate(
                              row.raised_at,
                              "d MMM, yyyy hh:mm a"
                            )}
                            {row.shipment_status ? ` · ${row.shipment_status}` : ""}
                          </p>
                          {viewerIsStaff && row.merchant_email && (
                            <p className="text-[11px] font-medium text-slate-700 break-all">
                              {row.merchant_email}
                            </p>
                          )}
                        </div>
                        <span className="text-xs font-bold text-rose-600">
                          + ₹{formatInrNumber(costDiff)}
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-2.5 text-xs">
                        <div>
                          <p className="text-[11px] text-slate-500">
                            Manifested
                          </p>
                          <p className="font-bold text-slate-900">
                            {manifestG} g
                          </p>
                          <p className="text-[10px] text-slate-500">
                            {row.manifested_dims || "Dimensions not recorded"}
                          </p>
                        </div>
                        <div>
                          <p className="text-[11px] text-slate-500">Charged</p>
                          <p className="font-bold text-slate-900">
                            {chargedG} g
                          </p>
                          <p className="text-[10px] text-slate-500">
                            {row.charged_dims || "Dimensions not recorded"}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center justify-between pt-1">
                        <button
                          type="button"
                          onClick={() => setSorterPreviewRow(row)}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-primary"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          View Image
                        </button>

                        {claimStatusUpper === CLAIM_STATUS.NONE ? (
                          canRaiseClaims ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => handleOpenCreateClaimForRow(row)}
                              className="h-7 text-xs text-primary border-primary/30"
                            >
                              Raise Claim
                            </Button>
                          ) : null
                        ) : (
                          <ClaimStatusBadge
                            row={row}
                            viewerIsStaff={viewerIsStaff}
                            needHelpHref={needHelpHref(row.tracking_id)}
                          />
                        )}
                      </div>
                      {canResolveClaims &&
                        claimStatusUpper === CLAIM_STATUS.CLAIM_RAISED && (
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={resolvingId === row.id}
                              onClick={() => handleOpenAdminResolve(row, "ACCEPTED")}
                              className="h-7 px-2 text-[11px] border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                            >
                              <CheckCircle2 className="h-3 w-3 mr-1" />
                              Accept
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={resolvingId === row.id}
                              onClick={() => handleOpenAdminResolve(row, "REJECTED")}
                              className="h-7 px-2 text-[11px] border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
                            >
                              <XCircle className="h-3 w-3 mr-1" />
                              Reject
                            </Button>
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

      <div className="text-xs text-slate-600 px-1">
        Showing{" "}
        <strong className="text-slate-900">{filteredDisputes.length}</strong>{" "}
        results
      </div>

      <Dialog
        open={Boolean(sorterPreviewRow)}
        onOpenChange={(open) => {
          if (!open) setSorterPreviewRow(null);
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-heading flex items-center gap-2">
              <Scale className="h-5 w-5 text-primary" />
              Weight Measurement Evidence
            </DialogTitle>
            <DialogDescription>
              Recorded weight &amp; dimension evidence for AWB{" "}
              {sorterPreviewRow?.tracking_id}
            </DialogDescription>
          </DialogHeader>

          {sorterPreviewRow && (
            <div className="space-y-4 py-2">
              <div className="rounded-xl border border-slate-200 bg-slate-900 text-white p-5 space-y-4">
                <div className="flex items-center justify-between text-xs text-slate-400 font-mono">
                  <span>AWB: {sorterPreviewRow.tracking_id}</span>
                  <span>
                    {safeFormatDate(sorterPreviewRow.raised_at, "d MMM, yyyy hh:mm a")}
                  </span>
                </div>

                {sorterPreviewRow.sorter_image_url ? (
                  <div className="flex flex-col items-center justify-center rounded-lg border border-slate-700 bg-slate-800 p-3 text-center space-y-2">
                    <img
                      src={sorterImageSrc ?? undefined}
                      alt={`Measurement evidence for AWB ${sorterPreviewRow.tracking_id}`}
                      className="max-h-56 w-auto rounded object-contain"
                    />
                    <p className="text-xs text-slate-300 font-mono">
                      Recorded Dimensions:{" "}
                      {sorterPreviewRow.charged_dims || "Dimensions not recorded"}
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 bg-slate-800 py-8 px-4 text-center space-y-2">
                    <Box className="h-12 w-12 text-slate-400" />
                    <p className="text-sm font-bold tracking-wide text-slate-200">
                      No measurement photo recorded
                    </p>
                    <p className="text-xs text-slate-300 font-mono">
                      Recorded Dimensions:{" "}
                      {sorterPreviewRow.charged_dims || "Dimensions not recorded"}
                    </p>
                  </div>
                )}

                <div className="grid grid-cols-3 gap-3 text-center text-xs">
                  <div className="rounded-lg bg-slate-800 p-2.5">
                    <p className="text-[10px] uppercase text-slate-400">
                      Manifested
                    </p>
                    <p className="text-sm font-bold text-slate-200 mt-0.5">
                      {getManifestedGrams(sorterPreviewRow)} g
                    </p>
                  </div>
                  <div className="rounded-lg bg-slate-800 p-2.5">
                    <p className="text-[10px] uppercase text-slate-400">
                      Charged
                    </p>
                    <p className="text-sm font-bold text-amber-400 mt-0.5">
                      {getChargedGrams(sorterPreviewRow)} g
                    </p>
                  </div>
                  <div className="rounded-lg bg-slate-800 p-2.5">
                    <p className="text-[10px] uppercase text-slate-400">
                      Billing Delta
                    </p>
                    <p className="text-sm font-bold text-rose-400 mt-0.5">
                      + ₹{formatInrNumber(getCostDiffInr(sorterPreviewRow))}
                    </p>
                  </div>
                </div>

                {getClaimedGrams(sorterPreviewRow) !== null && (
                  <p className="text-xs text-emerald-300 font-mono text-center">
                    Merchant Claimed: {getClaimedGrams(sorterPreviewRow)} g
                  </p>
                )}
              </div>

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setSorterPreviewRow(null)}
                >
                  Close Preview
                </Button>
                {canRaiseClaims &&
                  claimStatusOf(sorterPreviewRow) === CLAIM_STATUS.NONE && (
                  <Button
                    type="button"
                    onClick={() => {
                      const row = sorterPreviewRow;
                      setSorterPreviewRow(null);
                      handleOpenCreateClaimForRow(row);
                    }}
                    className="bg-primary text-primary-foreground hover:bg-primary/90"
                  >
                    Raise Claim for AWB
                  </Button>
                )}
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(resolveTarget)}
        onOpenChange={(open) => {
          if (!open) setResolveTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-md overflow-x-hidden">
          <DialogHeader className="min-w-0">
            <DialogTitle className="font-heading">
              {resolveTarget?.decision === "ACCEPTED"
                ? "Accept Weight Claim"
                : "Reject Weight Claim"}
            </DialogTitle>
            <DialogDescription>
              AWB {resolveTarget?.row.tracking_id} · Claimed:{" "}
              {resolveTarget ? getClaimedGrams(resolveTarget.row) ?? "—" : "—"} g
              vs Charged:{" "}
              {resolveTarget ? getChargedGrams(resolveTarget.row) : "—"} g
            </DialogDescription>
          </DialogHeader>

          {resolveTarget && (
            <div className="min-w-0 space-y-3 py-2 text-xs">
              {resolveTarget.decision === "ACCEPTED" ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-900 space-y-1">
                  <p className="font-semibold">
                    Accepting will re-rate the shipment at the merchant&apos;s
                    claimed weight ({getClaimedGrams(resolveTarget.row) ?? "—"} g)
                  </p>
                  <p className="text-emerald-800">
                    Maximum refundable surcharge delta: ₹
                    {formatInrNumber(getCostDiffInr(resolveTarget.row))}
                  </p>
                </div>
              ) : (
                <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-rose-900">
                  Rejecting keeps the charged weight (
                  {getChargedGrams(resolveTarget.row)} g) and closes the claim.
                </div>
              )}

              <div className="min-w-0 space-y-1.5">
                <Label className="text-xs text-slate-700">
                  Admin Resolution Remarks (Optional)
                </Label>
                <Textarea
                  rows={2}
                  value={adminResolveRemarks}
                  onChange={(e) => setAdminResolveRemarks(e.target.value)}
                  placeholder="Enter audit verification notes..."
                  className="min-w-0 w-full text-xs"
                />
              </div>

              <DialogFooter className="pt-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setResolveTarget(null)}
                  disabled={Boolean(resolvingId)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={handleConfirmAdminResolve}
                  disabled={Boolean(resolvingId)}
                  className={
                    resolveTarget.decision === "ACCEPTED"
                      ? "bg-emerald-600 text-white hover:bg-emerald-700"
                      : "bg-rose-600 text-white hover:bg-rose-700"
                  }
                  data-testid="weight-mismatch.resolve.confirm"
                >
                  {resolvingId && (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  )}
                  Confirm {resolveTarget.decision === "ACCEPTED" ? "Accept" : "Reject"}
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
