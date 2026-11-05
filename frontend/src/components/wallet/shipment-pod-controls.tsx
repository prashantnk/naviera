"use client";

import { PickupRead, PickupStatus } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { MeasurementDialog } from "@/components/shipments/measurement-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { downloadShipmentInvoicePdf } from "@/lib/api";
import { extractApiErrorMessage } from "@/lib/utils";
import {
  CheckCircle2,
  FileText,
  KeyRound,
  Loader2,
  Ruler,
  Share2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

interface ShipmentPodBannerProps {
  deliveryOtp?: string | null;
  podReceivedBy?: string | null;
  status: PickupStatus;
}

/**
 * Statuses in which the seller still needs the delivery OTP on screen: while the parcel
 * moves and, above all, when the rider is at the door (Out for delivery, audit D-02).
 */
const OTP_VISIBLE_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.IN_TRANSIT,
  PickupStatus.OUT_FOR_DELIVERY,
]);

export function ShipmentPodBanner({
  deliveryOtp,
  podReceivedBy,
  status,
}: ShipmentPodBannerProps) {
  if (OTP_VISIBLE_STATUSES.has(status) && deliveryOtp) {
    return (
      <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-amber-100 border border-amber-200 flex items-center justify-center text-amber-700 shrink-0">
            <KeyRound className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-extrabold text-amber-950">
              Delivery Verification OTP:{" "}
              <span className="font-mono text-base tracking-widest bg-white px-2.5 py-0.5 rounded border border-amber-300 text-amber-900">
                {deliveryOtp}
              </span>
            </p>
            <p className="text-xs text-amber-800 font-medium mt-0.5">
              Share with delivery partner at doorstep to verify Proof of
              Delivery (POD).
            </p>
          </div>
        </div>
        <Badge
          variant="outline"
          className="bg-amber-100 text-amber-900 border-amber-300 font-bold text-xs w-fit"
        >
          6-Digit OTP Active
        </Badge>
      </div>
    );
  }

  if (status === PickupStatus.COMPLETED && podReceivedBy) {
    return (
      <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-emerald-100 border border-emerald-200 flex items-center justify-center text-emerald-700 shrink-0">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-extrabold text-emerald-950">
              POD Verified via 6-Digit OTP — Received by: {podReceivedBy}
            </p>
            <p className="text-xs text-emerald-800 font-medium mt-0.5">
              Authenticated digital Proof of Delivery recorded in audit ledger.
            </p>
          </div>
        </div>
        <Badge
          variant="outline"
          className="bg-emerald-100 text-emerald-900 border-emerald-300 font-bold text-xs w-fit"
        >
          POD Verified
        </Badge>
      </div>
    );
  }

  return null;
}

interface ShipmentPodActionsProps {
  shipment: PickupRead;
  onRefresh: () => void;
}

export function ShipmentPodActions({
  shipment,
  onRefresh,
}: ShipmentPodActionsProps) {
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const { pending: downloadingInvoice, run: runInvoiceDownload } = useSingleFlight();
  const [measurementOpen, setMeasurementOpen] = useState(false);
  // Remounts the dialog per open, so every submission gets a fresh Idempotency-Key.
  const [measurementDialogKey, setMeasurementDialogKey] = useState(0);

  const handleDownloadInvoice = () => {
    void runInvoiceDownload(async () => {
      try {
        await downloadShipmentInvoicePdf(shipment.id, shipment.tracking_id);
        toast.success("GST Invoice PDF downloaded!");
      } catch (err: unknown) {
        toast.error(extractApiErrorMessage(err, "Failed to generate GST Invoice PDF."));
      }
    });
  };

  const handleShareTracking = () => {
    if (!shipment.tracking_id) return;
    const relativeUrl = routeTo(`/track/${shipment.tracking_id}`);
    const fullUrl =
      typeof window !== "undefined"
        ? `${window.location.origin}${relativeUrl}`
        : relativeUrl;
    navigator.clipboard.writeText(fullUrl).then(
      () => toast.success("Public tracking link copied to clipboard!"),
      () => toast.error("Could not copy the tracking link to the clipboard.")
    );
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        data-testid="shipment-detail.actions.download-invoice"
        onClick={handleDownloadInvoice}
        disabled={downloadingInvoice}
        className="font-semibold border-slate-200"
      >
        {downloadingInvoice ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <FileText className="mr-2 h-4 w-4 text-primary" />
        )}
        Download GST Invoice PDF
      </Button>

      {shipment.tracking_id && (
        <Button
          type="button"
          variant="outline"
          data-testid="shipment-detail.actions.share-tracking"
          onClick={handleShareTracking}
          className="font-semibold border-slate-200"
        >
          <Share2 className="mr-2 h-4 w-4 text-slate-600" />
          Share Tracking Link
        </Button>
      )}

      {capabilities.canOperate && (
        <>
          <Button
            type="button"
            variant="outline"
            data-testid="shipment-detail.actions.record-measurement"
            onClick={() => {
              setMeasurementDialogKey((key) => key + 1);
              setMeasurementOpen(true);
            }}
            className="font-semibold border-border"
          >
            <Ruler className="mr-2 h-4 w-4 text-primary" />
            Record measurement
          </Button>
          <MeasurementDialog
            key={measurementDialogKey}
            shipmentId={shipment.id}
            awbLabel={shipment.tracking_id || shipment.id.slice(0, 8).toUpperCase()}
            tenantSlug={tenantSlug}
            open={measurementOpen}
            onOpenChange={setMeasurementOpen}
            onRecorded={onRefresh}
          />
        </>
      )}
    </div>
  );
}
