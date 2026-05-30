// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/page.tsx
"use client";

import {
  PickupRead,
  PickupStatus,
  ShipmentActivityRead,
  ShipmentsService,
  ShipmentType,
} from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useUser } from "@/components/auth/auth-guard";
import { AdminTimeline } from "@/components/blocks/admin-timeline";
import { UpdateStatusDialog } from "@/components/forms/update-status-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { downloadShippingLabel } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase";
import { cn, formatTimeSlot } from "@/lib/utils";
import {
  ArrowLeft,
  Box,
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
  ShieldCheck,
  User,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

// Shared Status Color Mapping
const getStatusColor = (status: PickupStatus) => {
  switch (status) {
    case PickupStatus.DRAFT:
      return "bg-slate-100 text-slate-700 border-slate-200";
    case PickupStatus.OPEN:
      return "bg-sky-100 text-sky-700 border-sky-200";
    case PickupStatus.ASSIGNED:
      return "bg-indigo-100 text-indigo-700 border-indigo-200";
    case PickupStatus.IN_TRANSIT:
      return "bg-blue-100 text-blue-700 border-blue-200";
    case PickupStatus.COMPLETED:
      return "bg-emerald-100 text-emerald-700 border-emerald-200";
    case PickupStatus.CANCELLED:
      return "bg-rose-100 text-rose-700 border-rose-200";
    case PickupStatus.RTO_INITIATED:
      return "bg-amber-100 text-amber-700 border-amber-200";
    default:
      return "bg-slate-100 text-slate-700";
  }
};

export default function ShipmentDetailsPage() {
  const params = useParams();
  const shipmentId = params.id as string;
  const { routeTo, tenantSlug } = useTenant();
  const { isAdmin } = useUser();

  const [shipment, setShipment] = useState<PickupRead | null>(null);
  const [timeline, setTimeline] = useState<ShipmentActivityRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [isPrinting, setIsPrinting] = useState(false);

  const handleCopyTrackingId = () => {
    if (!shipment?.tracking_id) return;
    navigator.clipboard.writeText(shipment.tracking_id);
    toast.success("Tracking ID copied to clipboard!");
  };

  const fetchDetails = async () => {
    if (!shipmentId) return;
    try {
      const [shipmentData, timelineData] = await Promise.all([
        ShipmentsService.getShipmentDetails(shipmentId),
        ShipmentsService.getShipmentTimeline(shipmentId),
      ]);
      setShipment(shipmentData);
      setTimeline(timelineData);
    } catch (error) {
      console.error("Failed to fetch shipment details:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetails();
  }, [shipmentId]);

  const handlePrintLabel = async () => {
    setIsPrinting(true);
    try {
      await downloadShippingLabel(
        tenantSlug,
        shipmentId,
        shipment?.tracking_id || shipmentId
      );
    } catch (error) {
      toast.error("Failed to generate shipping label.");
    } finally {
      setIsPrinting(false);
    }
  };

  const handleSecureDownload = async (filePath: string, fileName: string) => {
    const supabase = getSupabaseClient(tenantSlug);
    const { data, error } = await supabase.storage
      .from("documents")
      .createSignedUrl(filePath, 60);

    if (error || !data) {
      toast.error("You do not have permission to view this document.");
      return;
    }
    window.open(data.signedUrl, "_blank");
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!shipment)
    return (
      <div className="p-8 text-center text-red-500">Shipment not found.</div>
    );

  const isReverse = shipment.shipment_type === ShipmentType.REVERSE;

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12 animate-in fade-in">
      {/* Header & Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button variant="outline" size="icon" asChild className="h-9 w-9">
            <Link href={routeTo("/shipments")}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-3">
              <span
                onClick={handleCopyTrackingId}
                className="cursor-pointer hover:opacity-80 active:scale-95 transition-all flex items-center gap-2 group select-none"
                title="Click to copy Tracking ID"
              >
                {shipment.tracking_id || "Pending Tracking ID"}
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
                className={cn(
                  "shadow-sm text-[10px] px-2.5 py-0.5 font-bold tracking-wider rounded-md uppercase",
                  getStatusColor(shipment.status)
                )}
              >
                {shipment.status.replace("_", " ")}
              </Badge>
            </h1>
            <p className="text-slate-500 text-sm mt-1">
              Ref: {shipment.order_reference_id || "N/A"}
            </p>
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handlePrintLabel}
            disabled={isPrinting}
          >
            {isPrinting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Printer className="mr-2 h-4 w-4" />
            )}
            Print Label
          </Button>

          {isAdmin && (
            <>
              <Button variant="outline" asChild>
                <Link href={routeTo(`/shipments/${shipment.id}/edit`)}>
                  <Pencil className="mr-2 h-4 w-4" /> Edit Details
                </Link>
              </Button>
              <UpdateStatusDialog
                shipmentId={shipment.id}
                currentStatus={shipment.status}
                onSuccess={fetchDetails}
              />
            </>
          )}
        </div>
      </div>

      {/* The Master Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-2">
        {/* ⬅️ LEFT COLUMN: Heavy Reading Data */}
        <div className="lg:col-span-2 space-y-6">
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
                <p className="text-sm text-slate-600 leading-relaxed">
                  {shipment.pickup_address.address_line1}
                </p>
                <p className="text-sm text-slate-600 leading-relaxed">
                  {shipment.pickup_address.city},{" "}
                  {shipment.pickup_address.state}{" "}
                  {shipment.pickup_address.pincode}
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
                <p className="text-sm text-slate-600 leading-relaxed">
                  {shipment.delivery_address.address_line1}
                </p>
                <p className="text-sm text-slate-600 leading-relaxed">
                  {shipment.delivery_address.city},{" "}
                  {shipment.delivery_address.state}{" "}
                  {shipment.delivery_address.pincode}
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
                {/* 🔥 NEW: Added Shipping Charge (Amount) */}
                <div className="space-y-1">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Shipping Charge
                  </p>
                  <p className="font-semibold text-slate-900">
                    ₹{shipment.payment_details.amount?.toFixed(2)}
                  </p>
                </div>

                <div className="space-y-1">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Cargo Value
                  </p>
                  <p className="font-semibold text-slate-900">
                    ₹{shipment.payment_details.declared_value}
                  </p>
                </div>

                {!isReverse && (
                  <>
                    <div className="space-y-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Tax Amount
                      </p>
                      <p className="font-semibold text-slate-900">
                        ₹{shipment.payment_details.tax_amount}
                      </p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Payment Mode
                      </p>
                      <p className="font-semibold text-slate-900">
                        {shipment.payment_details.payment_mode}
                      </p>
                    </div>
                  </>
                )}
                <div className="space-y-1">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    HSN Code
                  </p>
                  <p className="font-semibold text-slate-900">
                    {shipment.payment_details.hsn_code || "N/A"}
                  </p>
                </div>
                {!isReverse && (
                  <>
                    <div className="space-y-1 col-span-2 md:col-span-1">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        Invoice No.
                      </p>
                      <p className="font-semibold text-slate-900">
                        {shipment.payment_details.invoice_number || "N/A"}
                      </p>
                    </div>
                    <div className="space-y-1 col-span-2 md:col-span-2">
                      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                        E-Way Bill
                      </p>
                      <p className="font-semibold text-slate-900">
                        {shipment.payment_details.eway_bill_number || "N/A"}
                      </p>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Audit Log */}
          <AdminTimeline
            activities={timeline}
            trackingId={shipment.tracking_id}
          />
        </div>

        {/* ➡️ RIGHT SIDEBAR: Actionable & Status Data */}
        <div className="space-y-6">
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
                  Service Speed
                </span>
                <span className="font-bold text-slate-900">
                  {shipment.service_type}
                </span>
              </div>
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">Pickup Date</span>
                <span className="font-bold text-slate-900 flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5 text-slate-400" />
                  {new Date(
                    shipment.requested_pickup_date
                  ).toLocaleDateString()}
                </span>
              </div>
              {shipment.pickup_time_slot && (
                <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                  <span className="text-slate-500 font-medium">Pickup Window</span>
                  <span className="font-bold text-slate-900">
                    {formatTimeSlot(shipment.pickup_time_slot)}
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">Created On</span>
                <span className="font-bold text-slate-900">
                  {new Date(shipment.created_at).toLocaleDateString()}
                </span>
              </div>

              {/* 🔥 FIX: Render the Email instead of the UUID */}
              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium flex items-center gap-1.5"><User className="h-3.5 w-3.5" /> Booked By</span>
                <span 
                    className="font-semibold text-[11px] text-slate-700 bg-slate-100 px-2.5 py-0.5 rounded border border-slate-200" 
                    title={shipment.created_by_user_id}
                >
                  {/* If the email is available, show it. Otherwise fallback to the truncated ID */}
                  {shipment.creator_email || shipment.created_by_user_id?.split('-')[0] || "System"}
                </span>
              </div>

              <div className="flex justify-between items-center border-b border-slate-50 pb-3">
                <span className="text-slate-500 font-medium">Category</span>
                <span className="font-bold text-slate-900">
                  {shipment.product_category || "N/A"}
                </span>
              </div>

              {/* 🔥 NOW WORKING: Description */}
              {shipment.shipment_description && (
                <div className="space-y-1 pb-2">
                  <span className="text-slate-500 font-medium block">
                    Description
                  </span>
                  <span className="font-bold text-slate-900 block bg-slate-50 p-2.5 rounded-md border border-slate-100">
                    {shipment.shipment_description}
                  </span>
                </div>
              )}

              {/* 🔥 NOW WORKING: Return Reason */}
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

              {/* 🔥 NEW: Latest Status Comment Alert Box */}
              {shipment.latest_status_comment && (
                <div className="mt-4 bg-blue-50/50 p-3.5 rounded-lg border border-blue-100">
                  <span className="text-[10px] font-bold text-blue-800 uppercase tracking-widest flex items-center gap-1.5 mb-1.5">
                    <MessageSquare className="h-3.5 w-3.5" /> Latest Status Note
                  </span>
                  <p className="font-semibold text-blue-900 leading-snug italic">
                    "{shipment.latest_status_comment}"
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
              {shipment.packages.map((pkg, idx) => (
                <div
                  key={pkg.id || idx}
                  className="p-3 bg-slate-50 rounded-lg border border-slate-100 space-y-2 relative"
                >
                  <div className="flex justify-between items-start">
                    <span className="text-sm font-bold text-slate-900">
                      Box {idx + 1}
                    </span>
                    <span className="text-sm font-black text-slate-700 bg-white px-2 py-0.5 rounded shadow-sm border border-slate-100">
                      {pkg.weight} kg
                    </span>
                  </div>
                  <div className="text-xs font-medium text-slate-500 flex justify-between items-center">
                    <span>
                      {pkg.length} x {pkg.breadth} x {pkg.height} cm
                    </span>
                    {pkg.description && (
                      <span className="truncate ml-2 max-w-[120px] italic">
                        {pkg.description}
                      </span>
                    )}
                  </div>
                </div>
              ))}
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
                      onClick={() =>
                        handleSecureDownload(doc.file_url, doc.file_name)
                      }
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
