// frontend/src/components/carrier/delhivery-coordination-playbook.tsx
"use client";

/**
 * 3-Column Side-by-Side Co-ordination Playbook for Staff (`capabilities.canOperate`)
 * on Shipment Detail (`CarrierBillingPanel`).
 *
 * Gives Logismart Admin / Operations a crystal-clear side-by-side view of:
 *   1. What the customer booked on Logismart (with 1-click Copy Details for Delhivery).
 *   2. Exact steps to execute on `one.delhivery.com` (or with the Prime Partner Transporter).
 *   3. Exact steps back on Logismart to sync the AWB and settle any price difference.
 */
import { CheckCircle2, ChevronDown, ChevronUp, Clock, Copy, ExternalLink, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ServiceOption } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { serviceOptionLabel } from "./carrier-api";

export const DELHIVERY_PLAYBOOK_TESTID = "delhivery-coordination-playbook";
const DELHIVERY_ONE_URL = "https://one.delhivery.com";

export interface DelhiveryCoordinationPlaybookProps {
  shipmentId: string;
  serviceOption?: ServiceOption | string | null;
  carrierAwb?: string | null;
  transporterName?: string | null;
}

/**
 * Builds the plain-text summary copied to the clipboard when ops click
 * "Copy Details for Delhivery".
 *
 * @param shipmentId - Shipment UUID or tracking ID.
 * @param optionLabel - Human-readable service option label.
 * @param carrierAwb - Existing AWB/LRN if already assigned.
 * @param transporterName - Optional partner transporter name for Prime.
 * @returns Multi-line summary string for pasting into carrier notes/reference fields.
 */
function buildClipboardSummary(
  shipmentId: string,
  optionLabel: string,
  carrierAwb: string | null | undefined,
  transporterName: string | null | undefined,
): string {
  const lines = [
    `Logismart Shipment: ${shipmentId}`,
    `Service Option: ${optionLabel}`,
    `Carrier AWB Status: ${carrierAwb ? `Synced (${carrierAwb})` : "AWB Pending"}`,
  ];
  if (transporterName) {
    lines.push(`Transporter: ${transporterName}`);
  }
  return lines.join("\n");
}

/**
 * Renders the 3-column side-by-side co-ordination playbook card.
 */
export function DelhiveryCoordinationPlaybook({
  shipmentId,
  serviceOption,
  carrierAwb,
  transporterName,
}: DelhiveryCoordinationPlaybookProps) {
  const [expanded, setExpanded] = useState(true);

  const isPrime = serviceOption === ServiceOption.PRIME_SURFACE;
  const resolvedServiceLabel =
    serviceOptionLabel(serviceOption) ?? (isPrime ? "Logismart Prime" : "Delhivery Surface");
  const hasAwb = Boolean(carrierAwb && carrierAwb.trim().length > 0);
  const statusText = hasAwb ? `Synced: ${carrierAwb}` : "AWB Pending";
  const partnerName = transporterName?.trim() || "Partner";

  const handleCopyDetails = async () => {
    const summary = buildClipboardSummary(
      shipmentId,
      resolvedServiceLabel,
      carrierAwb,
      transporterName,
    );
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(summary);
      }
      toast.success("Copied shipment details for Delhivery co-ordination.");
    } catch {
      toast.error("Could not copy shipment details to clipboard.");
    }
  };

  return (
    <div
      data-testid={DELHIVERY_PLAYBOOK_TESTID}
      className="@container min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/80 p-3.5 space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-800 break-words">
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
            <span>Delhivery ↔ Logismart Co-ordination Playbook</span>
          </span>
          {!expanded && (
            <Badge
              variant="outline"
              className={
                hasAwb
                  ? "max-w-full whitespace-normal break-words border-emerald-300 bg-emerald-50 text-emerald-800 text-[11px] font-semibold h-auto py-0.5"
                  : "max-w-full whitespace-normal break-words border-amber-300 bg-amber-50 text-amber-900 text-[11px] font-semibold h-auto py-0.5"
              }
            >
              {hasAwb ? (
                <CheckCircle2 className="mr-1 h-3 w-3 shrink-0 text-emerald-700" aria-hidden="true" />
              ) : (
                <Clock className="mr-1 h-3 w-3 shrink-0 text-amber-700" aria-hidden="true" />
              )}
              {statusText}
            </Badge>
          )}
        </div>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setExpanded((prev) => !prev)}
          data-testid="delhivery-coordination.toggle"
          className="h-7 px-2 text-xs font-medium text-slate-600 hover:text-slate-900"
        >
          {expanded ? (
            <>
              Hide steps <ChevronUp className="ml-1 h-3.5 w-3.5" />
            </>
          ) : (
            <>
              Show 3-step playbook <ChevronDown className="ml-1 h-3.5 w-3.5" />
            </>
          )}
        </Button>
      </div>

      {expanded && (
        <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-3 min-w-0">
          {/* Column 1: On Logismart — Customer Order */}
          <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white p-3 flex flex-col justify-between space-y-2.5 shadow-2xs">
            <div className="min-w-0 space-y-2">
              <p className="text-xs font-bold text-slate-900 break-words">
                1. On Logismart — Customer Order
              </p>
              <div className="space-y-1 text-xs text-slate-600">
                <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                  <span className="text-slate-500">Booked option:</span>
                  <span className="font-semibold text-slate-900 break-words">{resolvedServiceLabel}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                  <span className="text-slate-500">Sync status:</span>
                  <span className="font-mono font-semibold text-slate-800 break-all">{statusText}</span>
                </div>
              </div>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleCopyDetails()}
              data-testid="delhivery-coordination.copy-btn"
              className="h-auto min-h-8 w-full min-w-0 max-w-full whitespace-normal py-1.5 text-xs font-semibold border-slate-200"
            >
              <Copy className="mr-1.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>Copy Details for Delhivery</span>
            </Button>
          </div>

          {/* Column 2: On one.delhivery.com / Transporter — Book & Dispatch */}
          <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white p-3 flex flex-col justify-between space-y-2.5 shadow-2xs">
            <div className="min-w-0 space-y-2 break-words">
              <p className="text-xs font-bold text-slate-900">
                2. On one.delhivery.com / Transporter — Book &amp; Dispatch
              </p>
              {isPrime ? (
                <ol className="space-y-1 text-xs text-slate-600 list-none">
                  <li>1. Print 3-Copy LR Docket &amp; 4x6 Box Labels</li>
                  <li>{`2. Hand over to assigned Prime Transporter (${partnerName})`}</li>
                  <li>3. Collect Transporter LR/GR number &amp; actual weight</li>
                </ol>
              ) : (
                <ol className="space-y-1 text-xs text-slate-600 list-none">
                  <li>1. Open one.delhivery.com -&gt; Orders -&gt; Create Order</li>
                  <li>2. Book shipment &amp; schedule Pickup Request</li>
                  <li>3. Copy generated Delhivery AWB &amp; billed amount</li>
                </ol>
              )}
            </div>

            {!isPrime && (
              <Button
                variant="outline"
                size="sm"
                asChild
                className="h-auto min-h-8 w-full min-w-0 max-w-full whitespace-normal py-1.5 text-xs font-semibold border-primary/30 text-primary hover:bg-primary/5"
              >
                <a
                  href={DELHIVERY_ONE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="delhivery-coordination.open-delhivery"
                >
                  <span>Open one.delhivery.com ↗</span>
                  <ExternalLink className="ml-1.5 h-3 w-3 shrink-0" aria-hidden="true" />
                </a>
              </Button>
            )}
          </div>

          {/* Column 3: Back on Logismart — Sync AWB & Settle Price */}
          <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white p-3 flex flex-col justify-between space-y-2 shadow-2xs">
            <div className="min-w-0 space-y-2 break-words">
              <p className="text-xs font-bold text-slate-900">
                3. Back on Logismart — Sync AWB &amp; Settle Price
              </p>
              <div className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                <p>
                  <span className="font-semibold text-slate-800">Step A:</span> Click{" "}
                  <span className="font-semibold text-slate-900">&ldquo;Enter carrier booking&rdquo;</span>{" "}
                  to save the Carrier AWB &amp; Charged Weight/Amount (links live tracking &amp; prints AWB on 4×6 label).
                </p>
                <p>
                  <span className="font-semibold text-slate-800">Step B:</span> If{" "}
                  <span className="font-semibold text-slate-900">Overpriced</span> or{" "}
                  <span className="font-semibold text-slate-900">Underpriced</span> (or after Hub Dimension Audit), click{" "}
                  <span className="font-semibold text-slate-900">&ldquo;Override / Adjust Price&rdquo;</span>{" "}
                  to set the <span className="font-mono">New Final Price (₹)</span> — Logismart automatically credits (<span className="font-mono">REFUND</span> + GST Credit Note) or debits (<span className="font-mono">SPEND</span> + GST Debit Note) the customer&apos;s wallet.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
