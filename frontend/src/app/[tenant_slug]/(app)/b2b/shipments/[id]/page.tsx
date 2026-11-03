"use client";

import {
  DocumentType,
  ExceptionsService,
  NdrAction,
  NdrExceptionReason,
  PickupRead,
  PickupStatus,
  ProductCategory,
  ShipmentActivityRead,
  ShipmentsService,
  ShipmentType,
} from "@/api_client";
import { useRepricePreview } from "@/components/shipments/use-reprice-preview";
import { RepricePreviewPanel } from "@/components/shipments/reprice-preview-panel";

import { useTenant } from "@/components/providers/tenant-provider";
import { useUser } from "@/components/auth/auth-guard";
import { AdminTimeline } from "@/components/blocks/admin-timeline";
import { UpdateStatusDialog } from "@/components/forms/update-status-dialog";
import { CreateAppointmentDialog } from "@/components/forms/create-appointment-dialog";
import { NextAddToPickupBanner } from "@/components/pickups/next-add-to-pickup-banner";
import { CarrierBillingPanel } from "@/components/carrier/carrier-billing-panel";
import { ChargesHistoryCard } from "@/components/shipments/charges-history-card";
import { freightBreakupLines } from "@/components/shipments/freight-lines";
import { formatInr } from "@/components/shipments/shipment-money";
import { splitPoNumbers } from "@/lib/validations/shipment";
import { canOpenShipmentEdit } from "@/components/shipments/edit-access";
import { getShipmentStatusBadgeClass } from "@/components/shipments/shipment-stage";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import {
  ShipmentPodActions,
  ShipmentPodBanner,
} from "@/components/wallet/shipment-pod-controls";
import { Edit } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { IconSelect } from "@/components/ui/icon-select";
import { PICKUP_TIME_SLOT_OPTIONS, toOptions, DOCUMENT_TYPE_OPTIONS } from "@/lib/form-options";
import { downloadShippingLabel } from "@/lib/api";
import { documentReferenceUrl, openDocument, uploadTenantDocument } from "@/lib/document-storage";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import { ServiceFlow } from "@/lib/workspace-flow";
import { format, parseISO } from "date-fns";
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  Clock,
  Copy,
  Download,
  FileText,
  Loader2,
  Printer,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

/** Appointment windows reuse the pickup slot metadata (same API values). */
const APPOINTMENT_SLOT_OPTIONS = toOptions(PICKUP_TIME_SLOT_OPTIONS);

const CATEGORY_LABELS: Record<string, string> = {
  HOUSEHOLD_PERSONAL: "Household & Personal",
  VEHICLE: "Vehicles & Automotive",
  DOCUMENTS: "Secure Documents",
  HAZARDOUS: "Hazardous & Chemicals",
  COMMERCIAL: "Commercial & Business Goods",
  ELECTRONICS: "Electronics & Appliances",
  APPAREL: "Apparel & Textiles",
  OTHER: "Other Goods",
};

export default function B2BShipmentDetailsPage() {
  const params = useParams();
  const shipmentId = params.id as string;
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();

  const [shipment, setShipment] = useState<PickupRead | null>(null);
  const [timeline, setTimeline] = useState<ShipmentActivityRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [isPrinting, setIsPrinting] = useState(false);
  // Bumped after every reload so the charges history refetches with the shipment.
  const [chargesRefreshKey, setChargesRefreshKey] = useState(0);

  // NDR Exception Resolution States
  const [uploading, setUploading] = useState(false);
  const [uploadDocumentType, setUploadDocumentType] = useState<DocumentType>(DocumentType.OTHER);
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedSlot, setSelectedSlot] = useState("");
  const [scheduling, setScheduling] = useState(false);

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

  const handleCancelOrder = async () => {
    if (!shipment) return;
    setIsCancelling(true);
    try {
      await ShipmentsService.cancelShipment(shipment.id);
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      toast.success(isPostPickupCancel ? "Shipment RTO initiated." : "Order cancelled successfully!");
      setShowCancelDialog(false);
      fetchDetails();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to cancel order."));
    } finally {
      setIsCancelling(false);
    }
  };

  const fetchDetails = useCallback(async () => {
    if (!shipmentId) return;
    try {
      const [shipmentData, timelineData] = await Promise.all([
        ShipmentsService.getShipmentDetails(shipmentId),
        ShipmentsService.getShipmentTimeline(shipmentId),
      ]);
      setShipment(shipmentData);
      setTimeline(timelineData);
      setChargesRefreshKey((key) => key + 1);
    } catch (error) {
      console.error("Failed to fetch B2B shipment details:", error);
      toast.error("Failed to load shipment details.");
    } finally {
      setLoading(false);
    }
  }, [shipmentId]);

  useEffect(() => {
    fetchDetails();
  }, [fetchDetails]);

  const handleCopyTrackingId = () => {
    if (!shipment?.tracking_id) return;
    navigator.clipboard.writeText(shipment.tracking_id);
    toast.success("Tracking ID copied to clipboard!");
  };

  const handlePrintLabel = async (labelFormat: "a4" | "thermal_4x2" = "a4") => {
    setIsPrinting(true);
    try {
      await downloadShippingLabel(
        tenantSlug,
        shipmentId,
        shipment?.tracking_id || shipmentId,
        labelFormat
      );
      toast.success(
        labelFormat === "thermal_4x2"
          ? "4x2 Thermal label PDF downloaded!"
          : "Consolidated shipping label PDF downloaded!"
      );
    } catch (error) {
      console.error("Print error:", error);
      toast.error("Failed to generate B2B shipping label.");
    } finally {
      setIsPrinting(false);
    }
  };

  // Safe Document Download Helper (D-18: stored bucket keys and URLs both open via a signed URL)
  const handleSecureDownload = async (filePath: string) => {
    if (!(filePath || "").trim()) {
      toast.error("Document link is missing.");
      return;
    }
    try {
      if (!(await openDocument(tenantSlug, filePath))) {
        toast.error("You do not have permission to view this document.");
      }
    } catch (err) {
      console.error(err);
      toast.error("Failed to fetch document download link.");
    }
  };

  // NDR File Dropzone Handler
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !shipment) return;

    if (file.size > 5 * 1024 * 1024) {
      toast.error("Compliance file size exceeds the 5MB limit.");
      return;
    }

    setUploading(true);
    try {
      const objectKey = await uploadTenantDocument(tenantSlug, file, "ndr");

      // Resolve the NDR via the merchant-accessible ExceptionsService (reference URL, signed on read: D-18)
      await ExceptionsService.applyExceptionAction(
        shipmentId,
        {
          action: NdrAction.UPLOAD_DOCUMENT,
          document_type: uploadDocumentType,
          document_url: documentReferenceUrl(objectKey),
          notes: `NDR Exception Resolved: Compliance document '${file.name}' uploaded.`,
        },
        tenantSlug,
      );

      toast.success("Compliance document successfully uploaded! Shipment status reset to In-Transit.");
      fetchDetails();
    } catch (err: unknown) {
      console.error(err);
      toast.error("Failed to upload document: " + extractApiErrorMessage(err, "Upload failed"));
    } finally {
      setUploading(false);
    }
  };

  // NDR Scheduling Handler
  const handleScheduleAppointment = async () => {
    if (!selectedDate || !selectedSlot || !shipment) {
      toast.error("Please select both a date and an appointment slot.");
      return;
    }

    setScheduling(true);
    try {
      // Parse slot in IST (+05:30, D-09): e.g. "10:00 - 14:00"
      const [startStr, endStr] = selectedSlot.split(" - ");
      const startIso = new Date(`${selectedDate}T${startStr}:00+05:30`);
      const endIso = new Date(`${selectedDate}T${endStr}:00+05:30`);

      const appointmentId = `APT-${Date.now()}`;

      // Resolve appointment exception via merchant-accessible ExceptionsService
      await ExceptionsService.applyExceptionAction(
        shipmentId,
        {
          action: NdrAction.BOOK_APPOINTMENT,
          appointment_start: startIso.toISOString(),
          appointment_end: endIso.toISOString(),
          notes: `Appointment ${appointmentId} scheduled for ${selectedDate} (${selectedSlot}).`,
        },
        tenantSlug,
      );

      toast.success("Delivery appointment scheduled! Shipment status reset to In-Transit.");
      fetchDetails();
    } catch (err: unknown) {
      console.error(err);
      toast.error("Failed to schedule appointment: " + extractApiErrorMessage(err, "Scheduling failed"));
    } finally {
      setScheduling(false);
    }
  };

  // Deterministic Boxes Generator for Table
  const boxes = useMemo(() => {
    if (!shipment) return [];
    if (shipment.is_blind_pickup) {
      const count = shipment.estimated_box_count || 0;
      return Array.from({ length: count }, (_, idx) => ({
        boxIndex: idx + 1,
        dimensions: "Hidden (Blind)",
        weight: "Hidden (Blind)",
        childAwb: `${shipment.tracking_id}-B${idx + 1}`,
      }));
    } else {
      const list: {
        boxIndex: number;
        dimensions: string;
        weight: string;
        childAwb: string;
      }[] = [];
      let boxCounter = 0;
      shipment.packages.forEach((pkg) => {
        for (let b = 0; b < (pkg.box_count || 0); b++) {
          boxCounter += 1;
          list.push({
            boxIndex: boxCounter,
            dimensions: `${pkg.length} x ${pkg.breadth} x ${pkg.height} ${pkg.dimension_unit}`,
            weight: `${pkg.weight} ${pkg.weight_unit}`,
            childAwb: `${shipment.tracking_id}-B${boxCounter}`,
          });
        }
      });
      return list;
    }
  }, [shipment]);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!shipment) {
    return (
      <div className="p-8 text-center text-red-500 font-bold">
        Shipment not found or access denied.
      </div>
    );
  }

  const isReverse = shipment.shipment_type === ShipmentType.REVERSE;
  const pricing = shipment.payment_details;

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12 animate-in fade-in duration-300">
      <NextAddToPickupBanner shipment={shipment} flow={ServiceFlow.B2B} />

      {/* Header Row */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-6">
        <div className="flex items-center gap-4">
          <Button variant="outline" size="icon" asChild className="h-9 w-9 shrink-0">
            <Link href={routeTo("/b2b/shipments")}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3 flex-wrap">
              <span
                onClick={handleCopyTrackingId}
                className="cursor-pointer hover:opacity-80 active:scale-95 transition-all flex items-center gap-2 group select-none font-mono"
                title="Click to copy Tracking ID"
              >
                <span data-testid="shipment-detail.header.awb">
                  {shipment.tracking_id || "Pending Tracking ID"}
                </span>
                {shipment.tracking_id && (
                  <Badge
                    variant="secondary"
                    className="text-[9px] py-0 px-2 text-slate-500 bg-slate-100 border border-slate-200 font-bold flex items-center gap-1 shadow-none group-hover:bg-primary/10 group-hover:text-primary group-hover:border-primary/20"
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
                  "shadow-sm text-[10px] px-2.5 py-0.5 font-bold tracking-wider rounded-md uppercase shrink-0",
                  getShipmentStatusBadgeClass(shipment.status)
                )}
              >
                {getShipmentStatusLabel(shipment.status)}
              </Badge>
              {capabilities.isStaff && shipment.transporter_name && (
                <Badge
                  variant="outline"
                  data-testid="shipment-detail.header.transporter"
                  className="shadow-sm text-[10px] px-2.5 py-0.5 font-bold tracking-wider rounded-md bg-amber-50 text-amber-900 border-amber-300 shrink-0"
                >
                  Transporter: {shipment.transporter_name}
                </Badge>
              )}
            </h1>
            <p className="text-slate-500 text-sm mt-1 font-semibold">
              Client Reference: {shipment.order_reference_id || "N/A"}
            </p>
          </div>
        </div>

        <div className="flex gap-2.5 flex-wrap">
          <Button
            variant="outline"
            className="font-bold border-slate-300 h-10 shadow-sm"
            onClick={() => handlePrintLabel("a4")}
            disabled={isPrinting}
            data-testid="shipment-detail.actions.download-label"
          >
            {isPrinting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin text-primary" />
            ) : (
              <Printer className="mr-2 h-4 w-4 text-slate-500" />
            )}
            Print Consolidated Label
          </Button>

          <Button
            variant="outline"
            className="font-bold border-slate-300 h-10 shadow-sm"
            onClick={() => handlePrintLabel("thermal_4x2")}
            disabled={isPrinting}
          >
            {isPrinting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin text-primary" />
            ) : (
              <Printer className="mr-2 h-4 w-4 text-primary" />
            )}
            Print 4x2 Thermal
          </Button>

          <ShipmentPodActions shipment={shipment} onRefresh={fetchDetails} />

          {capabilities.canWrite &&
            (shipment.status === PickupStatus.OPEN || shipment.status === PickupStatus.IN_TRANSIT) && (
            <CreateAppointmentDialog
              shipmentId={shipment.id}
              onSuccess={fetchDetails}
            />
          )}

          {canOpenShipmentEdit(capabilities, shipment.status) && (
            <Button
              variant="outline"
              className="font-bold border-slate-300 h-10 shadow-sm"
              asChild
              data-testid="shipment-detail.actions.edit"
            >
              <Link href={routeTo(`/b2b/shipments/${shipment.id}/edit`)}>
                <Edit className="mr-2 h-4 w-4 text-slate-500" />
                {capabilities.canOperate ? "Edit Shipment" : "Edit Order"}
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
                  className="font-semibold h-10 shadow-sm"
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

          {capabilities.canOperate && (
            <UpdateStatusDialog
              shipmentId={shipment.id}
              currentStatus={shipment.status}
              allowedNextStatuses={shipment.allowed_next_statuses}
              onSuccess={fetchDetails}
            />
          )}
        </div>
      </div>

      <ShipmentPodBanner
        deliveryOtp={shipment.delivery_otp}
        podReceivedBy={shipment.pod_received_by}
        status={shipment.status}
      />

      {/* Main Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* =====================================================================
            LEFT COLUMN: Freight Docket & Cargo Details
            ===================================================================== */}
        <div className="lg:col-span-2 min-w-0 space-y-6">
          {/* Digital Lorry Receipt (LR) Card */}
          <div className="bg-white rounded-xl shadow-sm overflow-hidden border-2 border-dashed border-slate-300 p-6 relative bg-amber-50/[0.04]">
            {/* Watermark/Label Docket Stamp */}
            <div className="absolute top-4 right-4 text-right">
              <span className="text-[9px] font-black tracking-widest text-slate-300 uppercase block border border-slate-200 rounded px-1.5 py-0.5 select-none">
                Official Docket
              </span>
            </div>

            <div className="space-y-6">
              {/* LR Docket Header */}
              <div className="border-b-2 border-dotted border-slate-200 pb-4">
                <h2 className="text-lg font-black text-slate-900 tracking-tight font-mono uppercase">
                  LORRY RECEIPT / FREIGHT DOCKET
                </h2>
                <div className="flex justify-between items-center mt-2 text-xs text-slate-500 font-semibold">
                  <span>LR Date: {format(new Date(shipment.created_at), "dd/MM/yyyy")}</span>
                  <span className="font-bold text-primary">
                    Payment Mode: {pricing?.freight_payment_mode?.replace("_", " ") || "N/A"}
                  </span>
                </div>
              </div>

              {/* Consignor/Consignee Info Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs border-b-2 border-dotted border-slate-200 pb-6">
                {/* Consignor (From) */}
                <div className="space-y-2">
                  <h4 className="font-bold text-slate-400 uppercase tracking-widest">Consignor (From)</h4>
                  <p className="font-bold text-slate-900 text-sm leading-tight">{shipment.pickup_address.name}</p>
                  {shipment.pickup_address.company_name && (
                    <p className="font-semibold text-slate-800">{shipment.pickup_address.company_name}</p>
                  )}
                  <p className="text-slate-600 leading-normal">{shipment.pickup_address.address_line1}</p>
                  {shipment.pickup_address.address_line2 && (
                    <p className="text-slate-600 leading-normal">{shipment.pickup_address.address_line2}</p>
                  )}
                  <p className="font-medium text-slate-700">
                    {shipment.pickup_address.city}, {shipment.pickup_address.state} - {shipment.pickup_address.pincode}
                  </p>
                  <p className="text-slate-500 font-semibold">Ph: {shipment.pickup_address.phone}</p>
                  <div className="pt-1">
                    <span className="font-mono bg-slate-100 text-slate-800 px-2 py-0.5 rounded border border-slate-200 font-bold">
                      GSTIN: {shipment.pickup_address.gstin || "N/A"}
                    </span>
                  </div>
                </div>

                {/* Consignee (To) */}
                <div className="space-y-2">
                  <h4 className="font-bold text-slate-400 uppercase tracking-widest">Consignee (To)</h4>
                  <p className="font-bold text-slate-900 text-sm leading-tight">{shipment.delivery_address.name}</p>
                  {shipment.delivery_address.company_name && (
                    <p className="font-semibold text-slate-800">{shipment.delivery_address.company_name}</p>
                  )}
                  <p className="text-slate-600 leading-normal">{shipment.delivery_address.address_line1}</p>
                  {shipment.delivery_address.address_line2 && (
                    <p className="text-slate-600 leading-normal">{shipment.delivery_address.address_line2}</p>
                  )}
                  <p className="font-medium text-slate-700">
                    {shipment.delivery_address.city}, {shipment.delivery_address.state} - {shipment.delivery_address.pincode}
                  </p>
                  <p className="text-slate-500 font-semibold">Ph: {shipment.delivery_address.phone}</p>
                  <div className="pt-1">
                    <span className="font-mono bg-slate-100 text-slate-800 px-2 py-0.5 rounded border border-slate-200 font-bold">
                      GSTIN: {shipment.delivery_address.gstin || "N/A"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Weight & Cargo details */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 border-b-2 border-dotted border-slate-200 pb-6 text-xs">
                <div className="bg-slate-50 p-3.5 rounded-lg border border-slate-200/60 space-y-1">
                  <span className="text-slate-500 font-bold uppercase tracking-wider block">Box Count</span>
                  <span className="text-sm font-extrabold text-slate-900 font-mono">
                    {shipment.is_blind_pickup ? `${shipment.estimated_box_count} (Blind)` : boxes.length} Boxes
                  </span>
                </div>
                <div className="bg-slate-50 p-3.5 rounded-lg border border-slate-200/60 space-y-1">
                  <span className="text-slate-500 font-bold uppercase tracking-wider block">Chargeable Weight</span>
                  <span className="text-sm font-extrabold text-slate-900 font-mono">
                    {pricing?.chargeable_weight?.toFixed(2) || "0.00"} KG
                  </span>
                </div>
                <div className="bg-slate-50 p-3.5 rounded-lg border border-slate-200/60 space-y-1">
                  <span className="text-slate-500 font-bold uppercase tracking-wider block">HSN / Category</span>
                  <span className="text-sm font-extrabold text-slate-900 truncate block">
                    {pricing?.hsn_code || "N/A"} / {CATEGORY_LABELS[shipment.product_category]?.split(" ")[0]}
                  </span>
                </div>
              </div>

              {/* Compliance documents the customer entered (Delhivery LR details: invoices, e-way bills, PO) */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 border-b-2 border-dotted border-slate-200 pb-6 text-xs" data-testid="shipment-detail.compliance">
                {[
                  { label: "GST Invoice No.", values: pricing?.invoice_numbers ?? [] },
                  { label: "E-Way Bill No.", values: pricing?.eway_bill_numbers ?? [] },
                  { label: "PO No.", values: splitPoNumbers(shipment.po_number) },
                ].map(({ label, values }) => (
                  <div key={label} className="space-y-1">
                    <span className="text-slate-500 font-bold uppercase tracking-wider block">{label}</span>
                    <span className="font-mono font-bold text-slate-900 break-all">
                      {values.length > 0 ? values.join(", ") : "—"}
                    </span>
                  </div>
                ))}
              </div>

              {/* Pricing Breakout Ledger */}
              {pricing && (
                <div className="space-y-4">
                  <h3 className="text-sm font-bold text-slate-900 font-mono uppercase tracking-wide">
                    Freight Pricing Breakout
                  </h3>
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/60 space-y-2 text-xs font-mono">
                    {/* Same rows as the quote the customer accepted (backend sell_lines). */}
                    {freightBreakupLines(pricing).map((line) => (
                      <div key={line.code} className="flex justify-between text-slate-600" data-testid={`shipment-detail.charges.line-${line.code.toLowerCase()}`}>
                        <span>{line.label}</span>
                        <span className="font-semibold text-slate-900">{formatInr(line.amount)}</span>
                      </div>
                    ))}
                    <div className="border-t border-slate-200 my-2 pt-2 flex justify-between text-slate-600">
                      <span>GST</span>
                      <span className="font-semibold text-slate-900">{formatInr(pricing.tax_amount ?? 0)}</span>
                    </div>

                    <div className="border-t border-double border-slate-300 my-2 pt-2 flex justify-between text-sm font-extrabold text-slate-900">
                      <span>TOTAL LOGISTICS COST</span>
                      <span>{formatInr(pricing.total_logistics_cost ?? 0)}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Child AWBs Table */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
              <h3 className="font-semibold text-slate-900 flex items-center gap-2">
                <FileText className="h-4.5 w-4.5 text-primary" />
                Cargo Package & Box Breakdown
              </h3>
              <Badge variant="secondary" className="font-bold bg-primary/10 text-primary shadow-sm border border-primary/20">
                {boxes.length} Box{boxes.length !== 1 ? "es" : ""}
              </Badge>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/50 text-slate-500 uppercase font-bold tracking-wider">
                    <th className="p-4">Box #</th>
                    <th className="p-4">Dimensions (LxBxH)</th>
                    <th className="p-4">Weight</th>
                    <th className="p-4">Child AWB / Label ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-semibold text-slate-700">
                  {boxes.map((box) => (
                    <tr key={box.boxIndex} className="hover:bg-slate-50/40">
                      <td className="p-4">Box {box.boxIndex}</td>
                      <td className="p-4">{box.dimensions}</td>
                      <td className="p-4 font-mono">{box.weight}</td>
                      <td className="p-4 font-mono font-bold text-primary select-all">{box.childAwb}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Technical Audit Timeline */}
          <AdminTimeline
            activities={timeline}
            trackingId={shipment.tracking_id}
          />
        </div>

        {/* =====================================================================
            RIGHT COLUMN: Operational Actions & NDR Exception Hub
            ===================================================================== */}
        <div className="min-w-0 space-y-6">
          {/* NDR Exception Hub Card */}
          {shipment.status === PickupStatus.EXCEPTION && (
            <div className="bg-white rounded-xl shadow-md overflow-hidden border-2 border-red-200 animate-in slide-in-from-top-4 duration-300 min-w-0">
              <div className="p-4 bg-red-50 border-b border-red-100 flex items-center gap-2.5 min-w-0">
                <AlertTriangle className="h-5 w-5 text-red-600 shrink-0" />
                <div className="min-w-0">
                  <h3 className="font-bold text-red-800 text-sm tracking-tight break-words">
                    NDR Exception Action Hub
                  </h3>
                  <span className="text-[10px] uppercase font-extrabold tracking-wider text-red-600 break-words">
                    Reason: {shipment.ndr_reason?.replace(/_/g, " ") || "UNSPECIFIED"}
                  </span>
                </div>
              </div>

              <div className="p-5 space-y-4 min-w-0">
                {/* Scenario A: DOCUMENT_NEEDED */}
                {shipment.ndr_reason === NdrExceptionReason.DOCUMENT_NEEDED && (
                  <div className="space-y-4 min-w-0">
                    <div className="p-3 bg-amber-50 rounded-lg border border-amber-100 text-xs text-amber-800 font-semibold leading-relaxed">
                      This shipment is on hold due to missing compliance documents. Select the document type and drop the required file below to resume transport automatically.
                    </div>

                    <div className="space-y-1.5 min-w-0">
                      <label className="text-xs font-bold text-slate-600 uppercase tracking-wider">Document Type</label>
                      <IconSelect
                        options={toOptions(DOCUMENT_TYPE_OPTIONS)}
                        value={uploadDocumentType}
                        onValueChange={(val) => setUploadDocumentType(val as DocumentType)}
                        disabled={uploading}
                      />
                    </div>

                    <div className="relative border-2 border-dashed border-slate-300 hover:border-primary rounded-xl p-8 text-center bg-slate-50 hover:bg-primary/5 transition-all cursor-pointer group min-w-0 overflow-hidden">
                      <input
                        type="file"
                        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                        onChange={handleFileUpload}
                        disabled={uploading}
                        accept=".pdf,.png,.jpg,.jpeg"
                      />
                      <div className="flex flex-col items-center gap-2">
                        {uploading ? (
                          <Loader2 className="h-10 w-10 animate-spin text-primary" />
                        ) : (
                          <UploadCloud className="h-10 w-10 text-slate-400 group-hover:text-primary transition-colors" />
                        )}
                        <span className="text-xs font-bold text-slate-700">
                          {uploading ? "Uploading compliance file..." : "Click or drag file here to upload"}
                        </span>
                        <span className="text-[10px] text-slate-400 font-medium">
                          Supports PDF, PNG, JPG (Max 5MB)
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Scenario B: APPOINTMENT_NEEDED */}
                {shipment.ndr_reason === NdrExceptionReason.APPOINTMENT_NEEDED && (
                  <div className="space-y-4 min-w-0">
                    <div className="p-3 bg-amber-50 rounded-lg border border-amber-100 text-xs text-amber-800 font-semibold leading-relaxed">
                      Corporate consignee requires a scheduled delivery slot. Select a date and window to log the appointment and resume transport.
                    </div>

                    <div className="space-y-3.5 text-xs min-w-0">
                      <div className="space-y-1.5 min-w-0">
                        <label className="font-bold text-slate-600 uppercase tracking-wider">Select Delivery Date</label>
                        <Input
                          type="date"
                          className="min-w-0 w-full bg-white border-slate-200 shadow-sm text-xs font-semibold h-10"
                          value={selectedDate}
                          onChange={(e) => setSelectedDate(e.target.value)}
                          min={new Date().toISOString().split("T")[0]}
                        />
                      </div>

                      <div className="space-y-1.5 min-w-0">
                        <label className="font-bold text-slate-600 uppercase tracking-wider">Select Time Slot</label>
                        <IconSelect
                          aria-label="Appointment time slot"
                          options={APPOINTMENT_SLOT_OPTIONS}
                          value={selectedSlot}
                          onValueChange={setSelectedSlot}
                          placeholder="Choose appointment slot"
                          triggerClassName="h-10 min-w-0 w-full border-slate-200 shadow-sm"
                        />
                      </div>

                      <Button
                        className="w-full min-w-0 max-w-full whitespace-normal font-bold h-auto min-h-10 py-2 mt-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow"
                        onClick={handleScheduleAppointment}
                        disabled={scheduling || !selectedDate || !selectedSlot}
                      >
                        {scheduling && <Loader2 className="mr-2 h-4 w-4 shrink-0 animate-spin text-primary-foreground" />}
                        <span>Confirm Appointment Slot</span>
                      </Button>
                    </div>
                  </div>
                )}

                {/* Fallback exception handling */}
                {shipment.ndr_reason !== NdrExceptionReason.DOCUMENT_NEEDED && shipment.ndr_reason !== NdrExceptionReason.APPOINTMENT_NEEDED && (
                  <div className="p-3 bg-red-50 text-red-800 rounded-lg border border-red-100 text-xs leading-relaxed font-semibold break-words">
                    The shipment is currently in an Exception state: {shipment.latest_status_comment || "Logistics exception logged."}
                  </div>
                )}

                <Button
                  asChild
                  variant="outline"
                  className="w-full min-w-0 max-w-full whitespace-normal h-auto min-h-9 py-1.5 text-xs font-bold border-rose-200 text-rose-800 hover:bg-rose-50"
                >
                  <Link href={routeTo("/b2b/delivery-exceptions")}>
                    Resolve in Exceptions & NDR
                  </Link>
                </Button>
              </div>
            </div>
          )}

          <CarrierBillingPanel shipmentId={shipment.id} tenantSlug={tenantSlug} carrierName={shipment.carrier_name} carrierAwb={shipment.carrier_awb} serviceOption={shipment.service_option} onSaved={fetchDetails} />
          {/* Charges history: every re-price with its debit / credit note (B14) */}
          <ChargesHistoryCard
            shipmentId={shipment.id}
            tenantSlug={tenantSlug}
            currentTotal={pricing?.total_logistics_cost}
            refreshKey={chargesRefreshKey}
          />

          {/* Order Specifications Overview Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2 shrink-0">
              <Clock className="h-4 w-4 text-primary" />
              <h3 className="font-semibold text-slate-900 text-sm">
                Operations Overview
              </h3>
            </div>
            <div className="p-5 space-y-3.5 text-xs font-semibold text-slate-600">
              <div className="flex justify-between items-center border-b border-slate-50 pb-2.5">
                <span className="text-slate-500 font-medium">Logistics Flow</span>
                <Badge variant={isReverse ? "destructive" : "default"} className="shadow-none rounded-md px-2 py-0">
                  {shipment.shipment_type}
                </Badge>
              </div>
              <div className="flex justify-between items-center border-b border-slate-50 pb-2.5">
                <span className="text-slate-500 font-medium">Service Speed</span>
                <span className="font-bold text-slate-900">{shipment.service_type.replace(/_/g, " ")}</span>
              </div>
              <div className="flex justify-between items-center border-b border-slate-50 pb-2.5">
                <span className="text-slate-500 font-medium">Booked Date</span>
                <span className="font-bold text-slate-900 flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5 text-slate-400" />
                  {format(parseISO(shipment.requested_pickup_date), "dd/MM/yyyy")}
                </span>
              </div>
              
              {shipment.appointment_id && (
                <div className="bg-primary/5 p-3 rounded-lg border border-primary/20 space-y-1.5 my-2">
                  <span className="text-[10px] uppercase font-extrabold tracking-wider text-primary block">
                    Confirmed Appointment
                  </span>
                  <div className="text-xs text-slate-800 font-mono font-bold">
                    ID: {shipment.appointment_id}
                  </div>
                  {shipment.appointment_start && shipment.appointment_end && (
                    <div className="text-[11px] text-slate-600 flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5 text-primary" />
                      {format(parseISO(shipment.appointment_start), "dd/MM/yyyy HH:mm")} - {format(parseISO(shipment.appointment_end), "HH:mm")}
                    </div>
                  )}
                </div>
              )}

              <div className="flex justify-between items-center border-b border-slate-50 pb-2.5">
                <span className="text-slate-500 font-medium">Product Category</span>
                <span className="font-bold text-slate-900">
                  {shipment.product_category === ProductCategory.OTHER
                    ? `Other (${shipment.other_category_description || "N/A"})`
                    : CATEGORY_LABELS[shipment.product_category] || "N/A"}
                </span>
              </div>
            </div>
          </div>

          {/* Compliance Documents List Card */}
          {shipment.documents && shipment.documents.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileText className="h-4.5 w-4.5 text-primary" />
                  <h3 className="font-semibold text-slate-900 text-sm">Compliance Documents</h3>
                </div>
                <Badge variant="secondary" className="font-bold bg-primary/10 text-primary border border-primary/20">
                  {shipment.documents.length}
                </Badge>
              </div>
              <div className="p-4 space-y-3">
                {shipment.documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100 group hover:border-primary/30 hover:bg-white transition-all"
                  >
                    <div className="flex flex-col min-w-0 pr-4">
                      <span className="text-xs font-bold text-slate-900 truncate group-hover:text-primary transition-colors">
                        {doc.document_type.replace(/_/g, " ")}
                      </span>
                      <span className="text-[10px] text-slate-500 truncate mt-0.5 font-medium">
                        {doc.file_name}
                      </span>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="shrink-0 bg-white shadow-sm font-bold text-xs h-8 px-2.5 hover:bg-primary/10 hover:text-primary hover:border-primary/30"
                      onClick={() => handleSecureDownload(doc.file_url)}
                    >
                      <Download className="w-3.5 h-3.5 mr-1" /> View
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
