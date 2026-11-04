// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/page.tsx
"use client";

import {
  ManifestResponse,
  ManifestsService,
  PickupRead,
  PickupStatus,
  ProductCategory,
  ShipmentActivityRead,
  ShipmentsService,
  ShipmentType,
} from "@/api_client";
import { useRepricePreview } from "@/components/shipments/use-reprice-preview";
import { RepricePreviewPanel } from "@/components/shipments/reprice-preview-panel";

import { useUser } from "@/components/auth/auth-guard";
import { AdminTimeline } from "@/components/blocks/admin-timeline";
import { UpdateStatusDialog } from "@/components/forms/update-status-dialog";
import { NextAddToPickupBanner } from "@/components/pickups/next-add-to-pickup-banner";
import { useTenant } from "@/components/providers/tenant-provider";
import { CarrierBillingPanel } from "@/components/carrier/carrier-billing-panel";
import { ChargesHistoryCard } from "@/components/shipments/charges-history-card";
import {
  pickupDateLabel,
  serviceLabel,
  stageTimestampLabel,
} from "@/components/shipments/shipment-display";
import { canOpenShipmentEdit } from "@/components/shipments/edit-access";
import { formatInr } from "@/components/shipments/shipment-money";
import {
  ShipmentStepperStage,
  getClosingStepLabel,
  getShipmentStage,
  getShipmentStatusBadgeClass,
  isRtoTrack,
  isShipmentPickedUp,
  isStepperStageReached,
} from "@/components/shipments/shipment-stage";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import { PICKUP_STATUS_OPTIONS } from "@/lib/form-options";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScreenGuideBanner, type GuideStep } from "@/components/ui/screen-guide-banner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  ShipmentPodActions,
  ShipmentPodBanner,
} from "@/components/wallet/shipment-pod-controls";
import { downloadShippingLabel } from "@/lib/api";
import { openDocument } from "@/lib/document-storage";
import {
  buildQueryCacheKey,
  getCachedQuery,
  hasCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { cn, extractApiErrorMessage, formatTimeSlot, safeFormatDate } from "@/lib/utils";
import { ServiceFlow } from "@/lib/workspace-flow";
import {
  AlertTriangle,
  ArrowLeft,
  Box,
  Building2,
  Calendar,
  Copy,
  CreditCard,
  FileText,
  Info,
  Loader2,
  MapPin,
  MessageSquare,
  Pencil,
  Printer,
  RotateCcw,
  ShieldCheck,
  Truck,
  User,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { CATEGORY_LABELS } from "../new/page";

const DISPUTES_BASE_ROUTE = "/disputes";
const MISMATCH_ROUTE_SEGMENT = "weight-mismatch";
const DISPUTES_MISMATCH_HREF = [
  DISPUTES_BASE_ROUTE,
  MISMATCH_ROUTE_SEGMENT,
].join("/");

const DEFAULT_SELLER_NAME = "Seller";
/** Shown when neither the seller profile nor the pickup address has a GSTIN (never invent one). */
const SELLER_GST_NOT_CONFIGURED = "Not Configured";

const SHIPMENT_CUSTOMER_GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "Print Label & Schedule Pickup",
    description:
      "Click Print Label for your 4×6 thermal label and add the order to a Pickup Request.",
  },
  {
    title: "Track 6-Stage Timeline",
    description:
      "Follow live scans from Manifested → Picked → In Transit → Out for Delivery → Delivered.",
  },
  {
    title: "Invoices & NDR Actions",
    description:
      "Download your GST Invoice or Credit/Debit Notes under Charges History, or act on NDR alerts.",
  },
];

const SHIPMENT_STAFF_GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "Book / Link Carrier AWB",
    description:
      "Use the Carrier Booking & Bill panel on the right to book on Delhivery or record the external AWB.",
  },
  {
    title: "1-Box Price Override & Weight Audit",
    description:
      "Enter a New Final Price (₹) or Record Measurement to automatically credit or debit the customer's wallet + issue a GST Note.",
  },
  {
    title: "Update Status & Doorstep OTP",
    description:
      "Click Update Status to move the parcel, verify the 6-digit delivery OTP, or initiate RTO.",
  },
];

const UNIT_LABELS: Record<string, string> = {
  KG: "kg",
  G: "grams",
  CM: "cm",
  M: "meters",
  IN: "inches",
  FT: "feet",
};

interface TrackingStageItem {
  id: string;
  label: string;
  completed: boolean;
  timestampLabel?: string;
  detailText?: string;
}

interface AuditMismatchSummary {
  oldKg: string;
  newKg: string;
  oldCharge?: string;
  newCharge?: string;
}

function _formatStageTimestamp(isoValue?: string | null): string | undefined {
  // Naive API timestamps are UTC; the stepper must show IST like the audit log (F-02).
  return stageTimestampLabel(isoValue);
}

function _extractAuditMismatch(
  activities: ShipmentActivityRead[]
): AuditMismatchSummary | null {
  for (const act of activities) {
    const diffRecord = act.diff as Record<string, unknown> | undefined;
    if (!diffRecord) continue;
    const chgDiff = diffRecord["chargeable_weight"] as
      | { old?: unknown; new?: unknown }
      | undefined;
    if (
      chgDiff &&
      chgDiff.old !== undefined &&
      chgDiff.new !== undefined
    ) {
      const costDiff = diffRecord["total_logistics_cost"] as
        | { old?: unknown; new?: unknown }
        | undefined;
      return {
        oldKg: Number(chgDiff.old).toFixed(2),
        newKg: Number(chgDiff.new).toFixed(2),
        oldCharge:
          costDiff?.old !== undefined
            ? Number(costDiff.old).toFixed(2)
            : undefined,
        newCharge:
          costDiff?.new !== undefined
            ? Number(costDiff.new).toFixed(2)
            : undefined,
      };
    }
  }
  return null;
}

function _buildTrackingStages(
  shipment: PickupRead,
  activities: ShipmentActivityRead[]
): TrackingStageItem[] {
  const findStatusActivity = (target: PickupStatus) => {
    for (let i = activities.length - 1; i >= 0; i -= 1) {
      const act = activities[i];
      const statusDiff = (act.diff as Record<string, unknown> | undefined)?.[
        "status"
      ] as { new?: string } | undefined;
      if (statusDiff?.new === target) {
        return act;
      }
    }
    return undefined;
  };

  // D-02: every flag below comes from the one shared status -> stage map.
  const status = shipment.status;
  const { isClosed } = getShipmentStage(status);
  const isRto = isRtoTrack(status);
  const isDelivered = status === PickupStatus.COMPLETED;
  const isInTransitOrBeyond = isShipmentPickedUp(status);
  const isOutForDeliveryOrBeyond = isStepperStageReached(
    status,
    ShipmentStepperStage.OUT_FOR_DELIVERY
  );
  const isScheduledOrBeyond =
    Boolean(shipment.manifest_id) ||
    isStepperStageReached(status, ShipmentStepperStage.PICKUP_SCHEDULED);
  const isReadyOrBeyond = isStepperStageReached(
    status,
    ShipmentStepperStage.READY_TO_SHIP
  );

  const openAct = findStatusActivity(PickupStatus.OPEN);
  const assignedAct = findStatusActivity(PickupStatus.ASSIGNED);
  const transitAct = findStatusActivity(PickupStatus.IN_TRANSIT);
  const outForDeliveryAct = findStatusActivity(PickupStatus.OUT_FOR_DELIVERY);
  const closingAct = isClosed ? findStatusActivity(status) : undefined;

  const manifestedTime = _formatStageTimestamp(shipment.created_at);
  const readyTime = _formatStageTimestamp(
    openAct?.timestamp || shipment.created_at
  );
  const scheduledTime = _formatStageTimestamp(assignedAct?.timestamp);
  const transitTime = _formatStageTimestamp(transitAct?.timestamp);
  const outForDeliveryTime = _formatStageTimestamp(outForDeliveryAct?.timestamp);
  const finalTime = _formatStageTimestamp(
    closingAct?.timestamp || (isClosed ? activities[0]?.timestamp : undefined)
  );

  const destinationLabel = `${shipment.delivery_address.city} (${shipment.delivery_address.state})`;
  const closingDetail = isDelivered
    ? `Delivered to consignee at ${destinationLabel}`
    : isClosed
    ? PICKUP_STATUS_OPTIONS[status].description
    : undefined;

  return [
    {
      id: "manifested",
      label: "Order manifested",
      completed: true,
      timestampLabel: manifestedTime,
    },
    {
      id: "ready",
      label: "Ready to ship",
      completed: isReadyOrBeyond,
      timestampLabel: isReadyOrBeyond ? readyTime : undefined,
    },
    {
      id: "pickup_scheduled",
      label: "Pickup scheduled",
      completed: isScheduledOrBeyond,
      timestampLabel: scheduledTime,
    },
    {
      id: "in_transit",
      label: "In-transit",
      completed: isInTransitOrBeyond,
      timestampLabel: transitTime,
      detailText: isInTransitOrBeyond
        ? transitAct?.comment ||
          `Parcel in transit towards ${destinationLabel}`
        : undefined,
    },
    {
      id: "out_for_delivery",
      label: "Out for delivery",
      completed: isOutForDeliveryOrBeyond,
      timestampLabel: outForDeliveryTime,
    },
    {
      id: isRto ? "rto" : "delivered",
      label: getClosingStepLabel(status),
      completed: isClosed,
      timestampLabel: finalTime,
      detailText: closingDetail,
    },
  ];
}

export default function ShipmentDetailsPage() {
  const params = useParams();
  const shipmentId = params.id as string;
  const { routeTo, tenantSlug } = useTenant();
  const { user, capabilities } = useUser();

  const detailCacheKey = buildQueryCacheKey(
    tenantSlug,
    "session",
    "shipment-detail",
    { shipmentId }
  );
  const cachedDetail = getCachedQuery<{
    shipment: PickupRead;
    timeline: ShipmentActivityRead[];
    linkedManifest: ManifestResponse | null;
  }>(detailCacheKey);

  const [shipment, setShipment] = useState<PickupRead | null>(
    () => cachedDetail?.shipment ?? null
  );
  const [linkedManifest, setLinkedManifest] = useState<ManifestResponse | null>(
    () => cachedDetail?.linkedManifest ?? null
  );
  const [timeline, setTimeline] = useState<ShipmentActivityRead[]>(
    () => cachedDetail?.timeline ?? []
  );
  const [loading, setLoading] = useState(
    () => !hasCachedQuery(detailCacheKey)
  );
  const [isPrinting, setIsPrinting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const isPostPickupCancel = shipment?.status === PickupStatus.IN_TRANSIT || shipment?.status === PickupStatus.OUT_FOR_DELIVERY;
  const canCancelPostPickup = !capabilities.isStaff || capabilities.canManageTeam;
  const cancelPreview = useRepricePreview(
    showCancelDialog && isPostPickupCancel && canCancelPostPickup ? shipment?.id : undefined,
    { status: PickupStatus.RTO_INITIATED },
    tenantSlug,
    { enabled: showCancelDialog && isPostPickupCancel && canCancelPostPickup }
  );

  // Bumped after every reload so the charges history refetches with the shipment.
  const [chargesRefreshKey, setChargesRefreshKey] = useState(0);

  const handleCancelOrder = async () => {
    if (!shipment) return;
    setIsCancelling(true);
    try {
      const updated = await ShipmentsService.cancelShipment(shipment.id);
      setShipment(updated);
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      const convertedToRto =
        updated?.status === PickupStatus.RTO_INITIATED || isPostPickupCancel;
      toast.success(
        convertedToRto
          ? "Shipment converted to Return to Origin (RTO). Applicable RTO charges have been applied."
          : "Order cancelled and prepaid wallet balance refunded!"
      );
      setShowCancelDialog(false);
      fetchDetails();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to cancel order"));
    } finally {
      setIsCancelling(false);
    }
  };

  const handleCopyTrackingId = () => {
    if (!shipment?.tracking_id) return;
    navigator.clipboard.writeText(shipment.tracking_id);
    toast.success("Tracking ID copied to clipboard!");
  };

  const fetchDetails = useCallback(async () => {
    if (!shipmentId) return;
    const cached = getCachedQuery<{
      shipment: PickupRead;
      timeline: ShipmentActivityRead[];
      linkedManifest: ManifestResponse | null;
    }>(detailCacheKey);
    if (cached !== null) {
      setShipment(cached.shipment);
      setTimeline(cached.timeline);
      setLinkedManifest(cached.linkedManifest);
      setLoading(false);
    }
    try {
      const [shipmentData, timelineData] = await Promise.all([
        ShipmentsService.getShipmentDetails(shipmentId),
        ShipmentsService.getShipmentTimeline(shipmentId),
      ]);
      setShipment(shipmentData);
      setTimeline(timelineData);
      setChargesRefreshKey((key) => key + 1);
      setCachedQuery(detailCacheKey, {
        shipment: shipmentData,
        timeline: timelineData,
        linkedManifest: null,
      });
      if (shipmentData.manifest_id) {
        ManifestsService.listManifests(undefined, undefined, undefined, tenantSlug)
          .then((manifests) => {
            const match = manifests.find((m) => m.id === shipmentData.manifest_id) ?? null;
            setLinkedManifest(match);
            setCachedQuery(detailCacheKey, {
              shipment: shipmentData,
              timeline: timelineData,
              linkedManifest: match,
            });
          })
          .catch(() => setLinkedManifest(null));
      } else {
        setLinkedManifest(null);
      }
    } catch (error) {
      console.error("Failed to fetch shipment details:", error);
    } finally {
      setLoading(false);
    }
  }, [shipmentId, tenantSlug, detailCacheKey]);

  useEffect(() => {
    fetchDetails();
  }, [fetchDetails]);

  const handlePrintLabel = async () => {
    setIsPrinting(true);
    try {
      await downloadShippingLabel(
        tenantSlug,
        shipmentId,
        shipment?.tracking_id || shipmentId
      );
    } catch {
      toast.error("Failed to generate shipping label.");
    } finally {
      setIsPrinting(false);
    }
  };

  const handleSecureDownload = async (filePath: string) => {
    if (!(filePath || "").trim()) {
      toast.error("Document link is missing.");
      return;
    }
    if (!(await openDocument(tenantSlug, filePath))) {
      toast.error("You do not have permission to view this document.");
    }
  };

  const trackingStages = useMemo(
    () => (shipment ? _buildTrackingStages(shipment, timeline) : []),
    [shipment, timeline]
  );

  const auditMismatch = useMemo(
    () => _extractAuditMismatch(timeline),
    [timeline]
  );

  if (loading && !shipment) {
    return (
      <div
        data-testid="shipment-detail-loading-skeleton"
        className="max-w-6xl mx-auto space-y-6 pb-12"
      >
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5 flex items-center gap-4">
          <Button variant="outline" size="icon" asChild className="h-9 w-9">
            <Link href={routeTo("/shipments")} prefetch={true}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="space-y-2 flex-1">
            <div className="h-7 w-56 rounded-lg bg-slate-100 animate-pulse" />
            <div className="h-4 w-80 rounded bg-slate-100 animate-pulse" />
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <div className="h-64 rounded-xl border border-slate-200 bg-white p-6 animate-pulse" />
            <div className="h-64 rounded-xl border border-slate-200 bg-white p-6 animate-pulse" />
          </div>
          <div className="h-96 rounded-xl border border-slate-200 bg-white p-6 animate-pulse" />
        </div>
      </div>
    );
  }

  if (!shipment)
    return (
      <div className="p-8 text-center text-rose-500">Shipment not found.</div>
    );

  const isReverse = shipment.shipment_type === ShipmentType.REVERSE;
  const disputeHref = routeTo(DISPUTES_MISMATCH_HREF);

  const sellerAddress = isReverse ? shipment.delivery_address : shipment.pickup_address;
  const sellerCompanyName =
    sellerAddress.company_name ||
    user?.company_name ||
    sellerAddress.name ||
    user?.full_name ||
    DEFAULT_SELLER_NAME;
  const sellerGstin =
    sellerAddress.gstin ||
    user?.gstin ||
    SELLER_GST_NOT_CONFIGURED;
  // Booking only manifests the order; the pickup date/slot exist once it is on a
  // pickup request (Delhivery "Add to pickup").
  const isOnPickupRequest = Boolean(shipment.manifest_id);
  const pickupDateText = pickupDateLabel(
    linkedManifest?.scheduled_date || shipment.requested_pickup_date,
    isOnPickupRequest
  );
  const effectivePickupSlot = isOnPickupRequest
    ? linkedManifest?.time_slot || shipment.pickup_time_slot
    : null;
  const bookedServiceLabel = serviceLabel(shipment);
  const pickupCityLine = `${shipment.pickup_address.city}, ${shipment.pickup_address.state}, ${shipment.pickup_address.pincode}`;
  const sellerCityLine = `${sellerAddress.city}, ${sellerAddress.state}, ${sellerAddress.pincode}`;

  const firstPkg = shipment.packages[0];
  const dimensionSummary = firstPkg
    ? `${firstPkg.length} x ${firstPkg.breadth} x ${firstPkg.height} ${
        UNIT_LABELS[firstPkg.dimension_unit as string] ||
        firstPkg.dimension_unit
      }`
    : "N/A";
  const chargeableVal =
    shipment.payment_details?.pricing_breakdown?.raw_chargeable_weight ||
    shipment.payment_details?.pricing_breakdown?.chargeable_weight ||
    shipment.payment_details?.chargeable_weight ||
    "N/A";
  const grandCargoValue = (
    shipment.payment_details?.shipment_total_value ?? 0
  ).toFixed(2);
  const shippingCostFormatted = (
    shipment.payment_details?.total_logistics_cost ?? 0
  ).toFixed(2);
  const cargoNetFormatted = (
    shipment.payment_details?.shipment_value ?? 0
  ).toFixed(2);
  const cargoTaxFormatted = (
    shipment.payment_details?.shipment_tax_value ?? 0
  ).toFixed(2);
  const baseFreightFormatted = (
    shipment.payment_details?.base_freight ?? 0
  ).toFixed(2);
  const gstTaxFormatted = (
    shipment.payment_details?.tax_amount ?? 0
  ).toFixed(2);
  const subtotalFormatted = (
    shipment.payment_details?.pricing_breakdown?.subtotal ?? 0
  ).toFixed(2);
  const speedPremiumNum = Number(
    shipment.payment_details?.pricing_breakdown?.service_surcharge ?? 0
  );
  const fuelSurchargeNum = Number(
    shipment.payment_details?.pricing_breakdown?.fuel_surcharge ?? 0
  );
  const networkSurchargeNum = Number(
    shipment.payment_details?.pricing_breakdown?.network_surcharge ?? 0
  );
  const oversizedSurchargeNum = Number(
    shipment.payment_details?.pricing_breakdown?.oversized_surcharge ?? 0
  );
  const collectionSurchargeNum = Number(
    shipment.payment_details?.pricing_breakdown?.cod_fee ?? 0
  );
  const naFallback = "N/A";
  const hsnLabel =
    shipment.payment_details?.hsn_code || naFallback;
  const actualMeasurementLabel =
    shipment.payment_details?.pricing_breakdown?.total_actual_weight ||
    naFallback;
  const volumetricMeasurementLabel =
    shipment.payment_details?.pricing_breakdown?.total_volumetric_weight ||
    naFallback;

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12 animate-in fade-in">
      <NextAddToPickupBanner shipment={shipment} flow={ServiceFlow.B2C} onAdded={fetchDetails} />

      <ScreenGuideBanner
        guideId="shipment-detail"
        title="How to Manage Your Shipment (3 Steps)"
        staffTitle="Staff Guide: Carrier Booking, 1-Box Price Override & Status"
        delhiveryEquivalent="Delhivery One: Order Details + Admin Controls"
        steps={SHIPMENT_CUSTOMER_GUIDE_STEPS}
        staffSteps={SHIPMENT_STAFF_GUIDE_STEPS}
        isStaff={capabilities.isStaff}
      />

      {/* Header & Actions */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5 space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Button variant="outline" size="icon" asChild className="h-9 w-9">
              <Link href={routeTo("/shipments")}>
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-3 flex-wrap">
                <span
                  onClick={handleCopyTrackingId}
                  className="cursor-pointer hover:opacity-80 active:scale-95 transition-all flex items-center gap-2 group select-none"
                  title="Click to copy Tracking ID"
                >
                  AWB{" "}
                  <span data-testid="shipment-detail.header.awb">
                    {shipment.tracking_id || "Pending Tracking ID"}
                  </span>
                  {shipment.tracking_id && (
                    <Badge
                      variant="secondary"
                      className="text-[10px] py-0.5 px-2 text-slate-500 bg-slate-100 border border-slate-200 font-semibold flex items-center gap-1 shadow-none group-hover:bg-primary/10 group-hover:text-primary group-hover:border-primary/20"
                    >
                      <Copy className="h-3 w-3 text-slate-400 group-hover:text-primary" />
                      Copy
                    </Badge>
                  )}
                </span>
                <Badge
                  variant="outline"
                  data-testid="shipment-detail.header.status"
                  className={cn(
                    "shadow-sm text-[10px] px-2.5 py-0.5 font-bold tracking-wider rounded-md uppercase",
                    getShipmentStatusBadgeClass(shipment.status)
                  )}
                >
                  {getShipmentStatusLabel(shipment.status)}
                </Badge>
              </h1>
              <p className="text-slate-500 text-xs font-medium mt-1">
                Order ID: #{shipment.order_reference_id || "N/A"} · Manifested
                on: {safeFormatDate(shipment.created_at, "dd MMM yyyy")}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {/* Customer returns (DTO) only make sense once the forward parcel was delivered (Delhivery parity). */}
            {capabilities.canBook && !isReverse && shipment.status === PickupStatus.COMPLETED && (
              <Button
                variant="outline"
                asChild
                className="font-semibold border-amber-200 bg-amber-50/60 text-amber-800 hover:bg-amber-100"
              >
                <Link
                  href={routeTo(
                    `/shipments/new/reverse?from_shipment_id=${shipment.id}`
                  )}
                >
                  <RotateCcw className="mr-2 h-4 w-4" /> Initiate Return (DTO)
                </Link>
              </Button>
            )}

            {capabilities.canBook &&
              (shipment.status === PickupStatus.DRAFT ||
              shipment.status === PickupStatus.OPEN ||
              shipment.status === PickupStatus.ASSIGNED ||
              shipment.status === PickupStatus.IN_TRANSIT ||
              shipment.status === PickupStatus.OUT_FOR_DELIVERY) && (
              <Dialog
                open={showCancelDialog}
                onOpenChange={setShowCancelDialog}
              >
                <DialogTrigger asChild>
                  <Button
                    variant="destructive"
                    className="font-semibold"
                    data-testid="shipment-detail.actions.cancel"
                  >
                    Cancel Order
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Cancel Order</DialogTitle>
                    <DialogDescription>
                      {isPostPickupCancel 
                        ? "Since this order has already been picked up, cancelling it will initiate an RTO (Return to Origin)."
                        : "Are you sure you want to cancel this order? This action cannot be undone."}
                    </DialogDescription>
                  </DialogHeader>

                  {isPostPickupCancel && !canCancelPostPickup && (
                    <div
                      role="alert"
                      data-testid="shipment-detail.cancel-rto-restricted"
                      className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs font-semibold text-amber-950"
                    >
                      Once picked up, cancelling a shipment initiates a paid Return to Origin (RTO). Only the shipper, Tenant Owner, or an Admin can initiate a manual RTO.
                    </div>
                  )}

                  {isPostPickupCancel && canCancelPostPickup && (
                    <RepricePreviewPanel 
                      preview={cancelPreview.preview} 
                      loading={cancelPreview.loading}
                      error={cancelPreview.error}
                      testIdPrefix="shipment-detail.cancel-preview"
                    />
                  )}

                  <DialogFooter>
                    <Button
                      variant="outline"
                      onClick={() => setShowCancelDialog(false)}
                      disabled={isCancelling}
                    >
                      Keep Order
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={handleCancelOrder}
                      disabled={
                        isCancelling ||
                        (isPostPickupCancel && (!canCancelPostPickup || cancelPreview.loading))
                      }
                      data-testid="shipment-detail.actions.cancel-confirm"
                    >
                      {isCancelling && (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      )}
                      Yes, Cancel Order
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}

            <Button
              variant="outline"
              onClick={handlePrintLabel}
              disabled={isPrinting}
              data-testid="shipment-detail.actions.download-label"
            >
              {isPrinting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Printer className="mr-2 h-4 w-4" />
              )}
              Print Label
            </Button>

            <ShipmentPodActions shipment={shipment} onRefresh={fetchDetails} />

            {canOpenShipmentEdit(capabilities, shipment.status) && (
              <Button variant="outline" asChild data-testid="shipment-detail.actions.edit">
                <Link href={routeTo(`/shipments/${shipment.id}/edit`)}>
                  <Pencil className="mr-2 h-4 w-4" />
                  {capabilities.canOperate ? "Edit Details" : "Edit Order"}
                </Link>
              </Button>
            )}

            {capabilities.canOperate && (
              <>
                <UpdateStatusDialog
                  shipmentId={shipment.id}
                  currentStatus={shipment.status}
                  allowedNextStatuses={shipment.allowed_next_statuses}
                  onSuccess={fetchDetails}
                />
              </>
            )}
          </div>
        </div>

        {/* Delhivery One Metadata Pills & Delivered Banner */}
        <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-slate-100">
          <Badge
            variant="outline"
            className="rounded-full px-3 py-0.5 text-[11px] font-semibold bg-sky-50 text-sky-700 border-sky-200"
          >
            Shipping method: {bookedServiceLabel}
          </Badge>
          {capabilities.isStaff && shipment.transporter_name && (
            <Badge
              variant="outline"
              data-testid="shipment-detail.header.transporter"
              className="rounded-full px-3 py-0.5 text-[11px] font-semibold bg-amber-50 text-amber-900 border-amber-300"
            >
              Transporter: {shipment.transporter_name}
            </Badge>
          )}
          {(shipment.status === PickupStatus.COMPLETED ||
            shipment.pod_received_by) && (
            <Badge
              variant="outline"
              className="rounded-full px-3 py-0.5 text-[11px] font-semibold bg-emerald-50 text-emerald-700 border-emerald-200"
            >
              Received by:{" "}
              {shipment.pod_received_by ||
                shipment.delivery_address.name ||
                "Consignee"}{" "}
              (Consignee)
            </Badge>
          )}
        </div>

        {shipment.status === PickupStatus.COMPLETED && (
          <div className="rounded-lg bg-emerald-50/70 border border-emerald-200/80 px-4 py-3 flex items-center gap-3">
            <Truck className="h-5 w-5 text-emerald-600 shrink-0" />
            <div>
              <p className="text-sm font-bold text-emerald-800">
                Delivered successfully
              </p>
              <p className="text-xs text-emerald-700">
                Your shipment has been successfully delivered to the consignee
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Reverse Return (DTO) & Doorstep QC Banner */}
      {isReverse && (
        <div className="bg-amber-50/80 border border-amber-200 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-2xs">
          <div className="flex items-start gap-3.5">
            <div className="h-10 w-10 rounded-lg bg-amber-100 border border-amber-200 flex items-center justify-center shrink-0 mt-0.5">
              <RotateCcw className="h-5 w-5 text-amber-700" />
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold text-amber-950 uppercase tracking-wider">
                  Reverse Return (DTO) & Doorstep QC
                </h3>
                <Badge
                  variant="outline"
                  className={
                    shipment.qc_required
                      ? "bg-emerald-100 text-emerald-800 border-emerald-300 text-[10px] font-bold"
                      : "bg-slate-100 text-slate-700 border-slate-200 text-[10px] font-bold"
                  }
                >
                  {shipment.qc_required
                    ? "Doorstep QC Required"
                    : "No QC Required"}
                </Badge>
              </div>
              <p className="text-xs font-semibold text-amber-900">
                Return Reason:{" "}
                <span className="font-normal">
                  {shipment.reason_for_return || "Customer Return"}
                </span>
              </p>
              {shipment.qc_notes && (
                <p className="text-xs text-amber-800">
                  QC Instructions:{" "}
                  <span className="italic">{shipment.qc_notes}</span>
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* NDR / Delivery Exception Banner */}
      {shipment.status === PickupStatus.EXCEPTION && (
        <div className="bg-rose-50/90 border border-rose-200 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-2xs">
          <div className="flex items-start gap-3.5">
            <div className="h-10 w-10 rounded-lg bg-rose-100 border border-rose-200 flex items-center justify-center shrink-0 mt-0.5">
              <AlertTriangle className="h-5 w-5 text-rose-700" />
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold text-rose-950 uppercase tracking-wider">
                  Delivery Exception (NDR) Requires Action
                </h3>
                {shipment.ndr_reason && (
                  <Badge
                    variant="outline"
                    className="bg-rose-100 text-rose-800 border-rose-300 text-[10px] font-bold"
                  >
                    {shipment.ndr_reason.replace(/_/g, " ")}
                  </Badge>
                )}
              </div>
              <p className="text-xs font-medium text-rose-900">
                {shipment.latest_status_comment ||
                  "Our delivery partner logged a non-delivery report. Submit reattempt, consignee update, or RTO instructions from the Exceptions workspace."}
              </p>
            </div>
          </div>
          <Button
            asChild
            className="shrink-0 font-bold bg-primary hover:bg-primary/90 text-primary-foreground shadow-sm"
          >
            <Link href={routeTo("/delivery-exceptions")}>
              Resolve in Exceptions & NDR
            </Link>
          </Button>
        </div>
      )}

      <ShipmentPodBanner
        deliveryOtp={shipment.delivery_otp}
        podReceivedBy={shipment.pod_received_by}
        status={shipment.status}
      />

      {/* The Master Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-2">
        {/* LEFT COLUMN: Tracking Stepper, Route, Financials, Audit Log */}
        <div className="lg:col-span-2 min-w-0 space-y-6">
          {/* Delhivery One 6-Stage Vertical Shipment Tracking Stepper */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
            <div className="flex items-center justify-between gap-2 mb-6 border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg bg-rose-50 border border-rose-100 flex items-center justify-center">
                  <Truck className="h-4 w-4 text-rose-600" />
                </div>
                <h3 className="text-base font-bold text-slate-900">
                  Shipment tracking
                </h3>
              </div>
              {shipment.status === PickupStatus.COMPLETED && (
                <Badge
                  variant="outline"
                  className="bg-emerald-50 text-emerald-700 border-emerald-200 text-xs font-semibold"
                >
                  Received by:{" "}
                  {shipment.pod_received_by ||
                    shipment.delivery_address.name ||
                    "Consignee"}{" "}
                  (Consignee)
                </Badge>
              )}
            </div>

            <div className="relative pl-6 space-y-5">
              {trackingStages.map((stage, idx) => {
                const isLast = idx === trackingStages.length - 1;
                const nextCompleted =
                  !isLast && Boolean(trackingStages[idx + 1]?.completed);
                return (
                  <div key={stage.id} className="relative">
                    {!isLast && (
                      <span
                        aria-hidden="true"
                        className={cn(
                          "absolute -left-[17px] top-4 -bottom-5 w-0.5",
                          nextCompleted ? "bg-emerald-500" : "bg-slate-200"
                        )}
                      />
                    )}
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute -left-[22px] top-1 h-3 w-3 rounded-full border-2",
                        stage.completed
                          ? "bg-emerald-500 border-emerald-500 ring-4 ring-emerald-50"
                          : "bg-white border-slate-300"
                      )}
                    />
                    <div className="space-y-0.5">
                      <p
                        className={cn(
                          "text-sm font-semibold",
                          stage.completed ? "text-slate-900" : "text-slate-400"
                        )}
                      >
                        {stage.label}
                      </p>
                      {(stage.timestampLabel || stage.detailText) && (
                        <p className="text-xs text-slate-500">
                          {stage.timestampLabel}
                          {stage.timestampLabel && stage.detailText
                            ? " · "
                            : ""}
                          {stage.detailText}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {auditMismatch && (
              <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <p className="text-sm font-bold text-amber-900">
                    Weight mismatch detected
                  </p>
                  <p className="text-xs font-medium text-amber-800">
                    Initial: {auditMismatch.oldKg} kg → Updated:{" "}
                    {auditMismatch.newKg} kg
                  </p>
                  {auditMismatch.oldCharge && auditMismatch.newCharge && (
                    <p className="text-xs text-amber-800">
                      Shipping charge ₹{auditMismatch.oldCharge} → ₹
                      {auditMismatch.newCharge}
                    </p>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                  className="bg-white border-amber-300 text-slate-900 hover:bg-amber-100 font-semibold text-xs shrink-0"
                >
                  <Link href={disputeHref}>Raise dispute</Link>
                </Button>
              </div>
            )}
          </div>

          {/* Route Details */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
            <div className="flex items-center gap-2 mb-6 border-b border-slate-100 pb-4">
              <MapPin className="h-5 w-5 text-primary" />
              <h3 className="text-lg font-semibold text-slate-900">
                Route Details
              </h3>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              <div className="space-y-1">
                <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                  Origin
                </p>
                <p className="font-semibold text-slate-900">
                  {shipment.pickup_address.name}
                </p>
                {shipment.pickup_address.company_name && (
                  <p className="text-xs font-bold text-primary/80 uppercase tracking-wider mt-0.5">
                    {shipment.pickup_address.company_name}
                  </p>
                )}
                {shipment.pickup_address.gstin && (
                  <p className="text-[10px] font-mono bg-slate-100 border border-slate-200/60 text-slate-600 px-1.5 py-0.5 rounded w-fit mt-1 uppercase tracking-wider font-bold">
                    GSTIN: {shipment.pickup_address.gstin}
                  </p>
                )}
                <p className="text-sm text-slate-600 leading-relaxed mt-1">
                  {shipment.pickup_address.address_line1}
                </p>
                <p className="text-sm text-slate-600 leading-relaxed">
                  {shipment.pickup_address.city},{" "}
                  {shipment.pickup_address.state}{" "}
                  {
                    shipment.pickup_address.pincode
                  }
                </p>
                <p className="text-sm text-slate-500 mt-2">
                  {shipment.pickup_address.phone}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                  Destination
                </p>
                <p className="font-semibold text-slate-900">
                  {shipment.delivery_address.name}
                </p>
                {shipment.delivery_address.company_name && (
                  <p className="text-xs font-bold text-primary/80 uppercase tracking-wider mt-0.5">
                    {shipment.delivery_address.company_name}
                  </p>
                )}
                {shipment.delivery_address.gstin && (
                  <p className="text-[10px] font-mono bg-slate-100 border border-slate-200/60 text-slate-600 px-1.5 py-0.5 rounded w-fit mt-1 uppercase tracking-wider font-bold">
                    GSTIN: {shipment.delivery_address.gstin}
                  </p>
                )}
                <p className="text-sm text-slate-600 leading-relaxed mt-1">
                  {shipment.delivery_address.address_line1}
                </p>
                <p className="text-sm text-slate-600 leading-relaxed">
                  {shipment.delivery_address.city},{" "}
                  {shipment.delivery_address.state}{" "}
                  {
                    shipment.delivery_address.pincode
                  }
                </p>
                <p className="text-sm text-slate-500 mt-2">
                  {shipment.delivery_address.phone}
                </p>
              </div>
            </div>
          </div>

          {/* Financials & Compliance */}
          {shipment.payment_details && (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
              <div className="flex items-center gap-2 mb-6 border-b border-slate-100 pb-4">
                <CreditCard className="h-5 w-5 text-primary" />
                <h3 className="text-lg font-semibold text-slate-900">
                  Financials & Compliance
                </h3>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                <div className="space-y-1">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Shipping Charge
                  </p>
                  <p className="font-semibold text-slate-900">
                    ₹{shippingCostFormatted}
                  </p>
                </div>

                <div className="space-y-1">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Cargo Value
                  </p>
                  <p className="font-semibold text-slate-900">
                    ₹{grandCargoValue}
                  </p>
                  <p className="text-[10px] text-slate-500">
                    (₹{cargoNetFormatted} net, ₹{cargoTaxFormatted} GST)
                  </p>
                </div>

                {!isReverse && (
                  <>
                    <div className="space-y-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Tax Amount
                      </p>
                      <p className="font-semibold text-slate-900">
                        ₹{gstTaxFormatted}
                      </p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Freight Billing
                      </p>
                      <p className="font-semibold text-slate-900 uppercase">
                        {
                          shipment.payment_details.freight_payment_mode?.replace(
                            "_",
                            " "
                          )
                        }
                      </p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        COD Collection
                      </p>
                      <p className="font-semibold text-emerald-600">
                        {
                          shipment.payment_details.is_cod
                            ? `₹${shipment.payment_details.cod_amount}`
                            : "Disabled"
                        }
                      </p>
                      {shipment.payment_details.is_cod && (
                        <p
                          className="text-xs font-medium text-slate-500"
                          data-testid="shipment-detail.payment.door-collectible"
                        >
                          Collect at door: {formatInr(shipment.door_collectible)}
                        </p>
                      )}
                    </div>
                  </>
                )}
                <div className="space-y-1">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    HSN Number
                  </p>
                  <p className="font-semibold text-slate-900">
                    {hsnLabel}
                  </p>
                </div>
                {!isReverse && (
                  <>
                    <div className="space-y-1 col-span-2 md:col-span-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Invoice No.
                      </p>
                      <p className="font-semibold text-slate-900">
                        {shipment.payment_details.invoice_number || naFallback}
                      </p>
                    </div>
                    <div className="space-y-1 col-span-2 md:col-span-2">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        E-Way Bill
                      </p>
                      <p className="font-semibold text-slate-900">
                        {shipment.payment_details.eway_bill_number || naFallback}
                      </p>
                    </div>
                  </>
                )}
              </div>

              <div className="mt-8 pt-6 border-t border-slate-200/80">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">
                  Billing & Measurement Ledger Breakup
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/60 space-y-3">
                    <h5 className="text-xs font-bold text-slate-500 uppercase tracking-wider border-b border-slate-200/60 pb-2">
                      Measurement Ledger
                    </h5>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between text-slate-600">
                        <span>
                          Chargeable Weight
                        </span>
                        <span className="font-bold text-slate-900">
                          {chargeableVal} kg
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-600">
                        <span>
                          Actual Weight
                        </span>
                        <span className="font-medium text-slate-800">
                          {actualMeasurementLabel} kg
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-600">
                        <span>
                          Volumetric Weight
                        </span>
                        <span className="font-medium text-slate-800">
                          {volumetricMeasurementLabel} kg
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Base & Surcharges Breakup */}
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/60 space-y-3">
                    <h5 className="text-xs font-bold text-slate-500 uppercase tracking-wider border-b border-slate-200/60 pb-2">
                      Base & Surcharges
                    </h5>
                    <div className="space-y-2 text-xs text-slate-600">
                      <div className="flex justify-between text-slate-700 text-sm">
                        <span>
                          Base Freight
                        </span>
                        <span className="font-semibold">
                          ₹{baseFreightFormatted}
                        </span>
                      </div>
                      {speedPremiumNum > 0 && (
                        <div className="flex justify-between pl-1">
                          <span>Speed Premium</span>
                          <span>₹{speedPremiumNum.toFixed(2)}</span>
                        </div>
                      )}
                      {fuelSurchargeNum > 0 && (
                        <div className="flex justify-between pl-1">
                          <span>Fuel Surcharge & DPH</span>
                          <span>₹{fuelSurchargeNum.toFixed(2)}</span>
                        </div>
                      )}
                      {networkSurchargeNum > 0 && (
                        <div className="flex justify-between pl-1">
                          <span>Network Surcharge</span>
                          <span>₹{networkSurchargeNum.toFixed(2)}</span>
                        </div>
                      )}
                      {oversizedSurchargeNum > 0 && (
                        <div className="flex justify-between text-amber-700 font-semibold pl-1">
                          <span>Oversized Surcharge</span>
                          <span>₹{oversizedSurchargeNum.toFixed(2)}</span>
                        </div>
                      )}
                      {collectionSurchargeNum > 0 && (
                        <div className="flex justify-between pl-1">
                          <span>
                            COD Processing Fee
                          </span>
                          <span>₹{collectionSurchargeNum.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Billing Ledger */}
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/60 space-y-3 flex flex-col justify-between">
                    <div>
                      <h5 className="text-xs font-bold text-slate-500 uppercase tracking-wider border-b border-slate-200/60 pb-2 mb-2">
                        Final Cost Breakup
                      </h5>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between text-slate-600">
                          <span>
                            Subtotal
                          </span>
                          <span className="font-medium text-slate-800">
                            ₹{subtotalFormatted}
                          </span>
                        </div>
                        <div className="flex justify-between text-slate-600">
                          <span>GST</span>
                          <span className="font-medium text-slate-800">
                            ₹{gstTaxFormatted}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex justify-between font-bold text-slate-900 border-t border-double border-slate-300 pt-2 mt-2 text-base">
                      <span>
                        Total logistics cost
                      </span>
                      <span>₹{shippingCostFormatted}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Audit Log */}
          <AdminTimeline
            activities={timeline}
            trackingId={shipment.tracking_id}
          />
        </div>

        {/* RIGHT SIDEBAR: Mismatch Banner, Order Summary, 3-Stop Addresses, Specs */}
        <div className="min-w-0 space-y-6">
          {/* Top-of-Rail Mismatch Card (matches snipit_0vdtck31dlp2o.png) */}
          {auditMismatch && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 flex flex-wrap items-center justify-between gap-3 shadow-xs min-w-0">
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-bold text-amber-900">
                  Weight mismatch detected
                </p>
                <p className="text-xs text-amber-800">
                  Initial: {auditMismatch.oldKg} kg → Updated:{" "}
                  {auditMismatch.newKg} kg
                </p>
                {auditMismatch.oldCharge && auditMismatch.newCharge && (
                  <p className="text-xs text-amber-800">
                    Shipping charge ₹{auditMismatch.oldCharge} → ₹
                    {auditMismatch.newCharge}
                  </p>
                )}
              </div>
              <Button
                size="sm"
                asChild
                className="bg-amber-400 hover:bg-amber-500 text-slate-950 font-bold text-xs shrink-0"
              >
                <Link href={disputeHref}>Raise dispute</Link>
              </Button>
            </div>
          )}

          {/* Delhivery One Order Summary Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden min-w-0">
            <div className="p-4 border-b border-slate-100 flex items-center gap-2">
              <CreditCard className="h-4 w-4 text-rose-600" />
              <h3 className="font-bold text-slate-900">Order summary</h3>
            </div>
            <div className="p-4 space-y-4">
              {/* Box details sub-card */}
              <div className="rounded-xl bg-slate-50/80 border border-slate-100 p-3.5 space-y-3">
                <p className="text-xs font-semibold text-slate-600">
                  Box details
                </p>
                <div className="grid grid-cols-2 gap-3 border-b border-slate-200/70 pb-3">
                  <div>
                    <p className="text-[11px] text-slate-400">Box count</p>
                    <p className="text-xs font-bold text-slate-900 mt-0.5">
                      {shipment.packages.length}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-400">Dimension</p>
                    <p className="text-xs font-bold text-slate-900 mt-0.5">
                      {dimensionSummary}
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-500 flex items-center gap-1.5">
                    <span>
                      Chargeable weight
                    </span>
                    {auditMismatch && (
                      <Badge
                        variant="outline"
                        className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[10px] py-0 px-1.5"
                      >
                        Updated
                      </Badge>
                    )}
                  </span>
                  <span className="font-bold text-slate-900">
                    {chargeableVal} kg
                  </span>
                </div>
              </div>

              {/* Invoice details sub-card */}
              <div className="rounded-xl bg-slate-50/80 border border-slate-100 p-3.5 space-y-3">
                <p className="text-xs font-semibold text-slate-600">
                  Invoice details
                </p>
                <div className="border-b border-slate-200/70 pb-2.5">
                  <p className="text-[11px] text-slate-400">Payment mode</p>
                  <p className="text-xs font-bold text-slate-900 mt-0.5">
                    {
                      shipment.payment_details?.is_cod ? "COD" : "Prepaid"
                    }
                  </p>
                </div>
                <div className="border-b border-slate-200/70 pb-2.5 space-y-1">
                  <p className="text-[11px] text-slate-400">Payment details</p>
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-slate-700">
                      Grand{" "}
                      <span>
                        total
                      </span>
                    </span>
                    <span className="text-slate-400">
                      {shipment.packages.length} Item(s)
                    </span>
                    <span className="font-bold text-slate-900">
                      ₹{grandCargoValue}
                    </span>
                  </div>
                </div>
                <div>
                  <p className="text-[11px] text-slate-400">Billing address</p>
                  <p className="text-xs font-bold text-slate-900 uppercase mt-0.5">
                    {shipment.delivery_address.name}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <CarrierBillingPanel shipmentId={shipment.id} tenantSlug={tenantSlug} carrierName={shipment.carrier_name} carrierAwb={shipment.carrier_awb} serviceOption={shipment.service_option} shipmentStatus={shipment.status} onSaved={fetchDetails} />
          {/* Charges history: every re-price with its debit / credit note (B14) */}
          <ChargesHistoryCard
            shipmentId={shipment.id}
            tenantSlug={tenantSlug}
            currentTotal={shipment.payment_details?.total_logistics_cost}
            refreshKey={chargesRefreshKey}
          />

          {/* Delhivery One 3-Stop Vertical Address Timeline Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="p-4 border-b border-slate-100 flex items-center gap-2">
              <MapPin className="h-4 w-4 text-rose-600" />
              <h3 className="font-bold text-slate-900">Addresses</h3>
            </div>
            <div className="p-5">
              <div className="relative pl-6 space-y-6 before:absolute before:left-[7px] before:top-2 before:bottom-2 before:w-px before:border-l before:border-dashed before:border-slate-300">
                {/* Stop 1: Pickup address */}
                <div className="relative">
                  <span
                    aria-hidden="true"
                    className="absolute -left-[22px] top-1 h-3 w-3 rounded-full border-2 border-slate-900 bg-white"
                  />
                  <p className="text-[11px] font-medium text-slate-400">
                    Pickup address
                  </p>
                  <p className="text-xs font-bold text-slate-900 uppercase mt-0.5">
                    {shipment.pickup_address.company_name ||
                      shipment.pickup_address.name}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {pickupCityLine}
                  </p>
                </div>

                {/* Stop 2: Seller address */}
                <div className="relative">
                  <span
                    aria-hidden="true"
                    className="absolute -left-[24px] top-0.5 h-4 w-4 rounded bg-rose-50 border border-rose-200 flex items-center justify-center"
                  >
                    <Building2 className="h-2.5 w-2.5 text-rose-600" />
                  </span>
                  <p className="text-[11px] font-medium text-slate-400">
                    Seller address
                  </p>
                  <p className="text-xs font-bold text-slate-900 uppercase mt-0.5">
                    {sellerCompanyName}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {sellerCityLine} · GST: {sellerGstin}
                  </p>
                </div>

                {/* Stop 3: Delivery address */}
                <div className="relative">
                  <span
                    aria-hidden="true"
                    className="absolute -left-[22px] top-1 h-3 w-3 rounded-xs border-2 border-rose-500 bg-white"
                  />
                  <p className="text-[11px] font-medium text-slate-400">
                    Delivery address
                  </p>
                  <p className="text-xs font-bold text-slate-900 uppercase mt-0.5">
                    {shipment.delivery_address.name}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {shipment.delivery_address.address_line1},{" "}
                    {shipment.delivery_address.city},{" "}
                    {shipment.delivery_address.state},{" "}
                    {
                      shipment.delivery_address.pincode
                    }
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Order Specifications Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2 shrink-0">
              <Info className="h-4 w-4 text-primary" />
              <h3 className="font-semibold text-slate-900">
                Order Specifications
              </h3>
            </div>
            <div className="p-5 space-y-4 text-sm">
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">
                  Logistics Flow
                </span>
                <Badge
                  variant={isReverse ? "destructive" : "default"}
                  className="shadow-none rounded-md px-2 py-0"
                >
                  {shipment.shipment_type}
                </Badge>
              </div>
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">
                  Service
                </span>
                <span className="font-bold text-slate-900">
                  {bookedServiceLabel}
                </span>
              </div>
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">Pickup Date</span>
                <span className="font-bold text-slate-900 flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5 text-slate-400" />
                  {pickupDateText}
                </span>
              </div>
              {effectivePickupSlot && (
                <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                  <span className="text-slate-500 font-medium">
                    Pickup Window
                  </span>
                  <span className="font-bold text-slate-900">
                    {formatTimeSlot(effectivePickupSlot)}
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">Created On</span>
                <span className="font-bold text-slate-900">
                  {safeFormatDate(shipment.created_at, "dd MMM yyyy")}
                </span>
              </div>

              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium flex items-center gap-1.5">
                  <User className="h-3.5 w-3.5" /> Booked By
                </span>
                <span
                  className="font-semibold text-[11px] text-slate-700 bg-slate-100 px-2.5 py-0.5 rounded border border-slate-200"
                  title={shipment.created_by_user_id}
                >
                  {shipment.creator_email ||
                    shipment.created_by_user_id?.split("-")[0] ||
                    "System"}
                </span>
              </div>

              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">Category</span>
                <span className="font-bold text-slate-900">
                  {shipment.product_category === ProductCategory.OTHER
                    ? `Other (${shipment.other_category_description || "N/A"})`
                    : CATEGORY_LABELS[shipment.product_category] || "N/A"}
                </span>
              </div>

              {isReverse && shipment.reason_for_return && (
                <div className="mt-4 bg-rose-50 p-3.5 rounded-lg border border-rose-100">
                  <span className="text-[10px] font-bold text-rose-800 uppercase tracking-widest flex items-center gap-1.5 mb-1.5">
                    <ShieldCheck className="h-3.5 w-3.5" /> Return Reason
                  </span>
                  <p className="font-semibold text-rose-900 leading-snug">
                    {shipment.reason_for_return}
                  </p>
                </div>
              )}

              {shipment.latest_status_comment && (
                <div className="mt-4 bg-sky-50/50 p-3.5 rounded-lg border border-sky-100">
                  <span className="text-[10px] font-bold text-sky-800 uppercase tracking-widest flex items-center gap-1.5 mb-1.5">
                    <MessageSquare className="h-3.5 w-3.5" /> Latest Status Note
                  </span>
                  <p className="font-semibold text-sky-900 leading-snug italic">
                    &quot;{shipment.latest_status_comment}&quot;
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Packages Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col lg:max-h-[400px]">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <Box className="h-4 w-4 text-primary" />
                <h3 className="font-semibold text-slate-900">Packages</h3>
              </div>
              <Badge
                variant="secondary"
                className="font-bold bg-white border-slate-200 shadow-sm"
              >
                {shipment.packages.length}
              </Badge>
            </div>
            <div className="p-4 space-y-3 overflow-y-auto">
              {shipment.packages.map((pkg, idx) => {
                const pkgMeasurement =
                  UNIT_LABELS[pkg.weight_unit as string] || pkg.weight_unit;
                return (
                  <div
                    key={pkg.id || idx}
                    className="p-3 bg-slate-50 rounded-lg border border-slate-100 space-y-2 relative"
                  >
                    <div className="flex justify-between items-start">
                      <span className="text-sm font-bold text-slate-900">
                        Box {idx + 1}
                      </span>
                      <span className="text-sm font-black text-slate-700 bg-white px-2 py-0.5 rounded shadow-sm border border-slate-100">
                        {
                          pkg.weight
                        }{" "}
                        {pkgMeasurement}
                      </span>
                    </div>
                    <div className="text-xs font-medium text-slate-500 flex justify-between items-center">
                      <span>
                        {pkg.length} x {pkg.breadth} x {pkg.height}{" "}
                        {UNIT_LABELS[pkg.dimension_unit as string] ||
                          pkg.dimension_unit}
                      </span>
                      {pkg.description && (
                        <span className="truncate ml-2 max-w-[120px] italic">
                          {pkg.description}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Secure Documents Card */}
          {shipment.documents && shipment.documents.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-primary" />
                  <h3 className="font-semibold text-slate-900">Documents</h3>
                </div>
                <Badge
                  variant="secondary"
                  className="font-bold bg-white border-slate-200 shadow-sm"
                >
                  {shipment.documents.length}
                </Badge>
              </div>
              <div className="p-4 space-y-3">
                {shipment.documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100 group hover:border-primary/30 transition-colors"
                  >
                    <div className="flex flex-col min-w-0 pr-4">
                      <span className="text-sm font-bold text-slate-900 truncate group-hover:text-primary transition-colors">
                        {doc.document_type.replace(/_/g, " ")}
                      </span>
                      <span className="text-xs text-slate-500 truncate mt-0.5">
                        {doc.file_name}
                      </span>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="shrink-0 bg-white shadow-sm font-semibold"
                      onClick={() => handleSecureDownload(doc.file_url)}
                    >
                      View
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
