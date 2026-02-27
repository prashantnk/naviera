// src/app/[tenant_slug]/(app)/shipments/[id]/page.tsx
"use client";

import { PickupRead, ShipmentActivityRead, ShipmentsService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useUser } from "@/components/auth/auth-guard";
import { AdminTimeline } from "@/components/blocks/admin-timeline";
import { UpdateStatusDialog } from "@/components/forms/update-status-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { downloadShippingLabel } from "@/lib/api";
import { ArrowLeft, ArrowRight, Box, Loader2, MapPin, PackageSearch, Pencil, Printer } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

export default function ShipmentDetailsPage() {
    const params = useParams();
    const shipmentId = params.id as string;
    const { routeTo, tenantSlug } = useTenant();
    const { isAdmin } = useUser();

    const [shipment, setShipment] = useState<PickupRead | null>(null);
    const [timeline, setTimeline] = useState<ShipmentActivityRead[]>([]);
    const [loading, setLoading] = useState(true);
    const [isPrinting, setIsPrinting] = useState(false);

    const fetchDetails = async () => {
        if (!shipmentId) return;
        try {
            const [shipmentData, timelineData] = await Promise.all([
                ShipmentsService.getShipmentDetails(shipmentId),
                ShipmentsService.getShipmentTimeline(shipmentId)
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
            await downloadShippingLabel(tenantSlug, shipmentId, shipment?.tracking_id || shipmentId);
        } catch (error) {
            console.error("Print Error:", error);
            toast.error("Failed to generate shipping label.");
        } finally {
            setIsPrinting(false);
        }
    };

    if (loading) {
        return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>;
    }

    if (!shipment) {
        return <div className="p-8 text-center text-red-500">Shipment not found.</div>;
    }

    return (
        <div className="max-w-5xl mx-auto space-y-6 pb-12">

            {/* Header & Actions */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                    <Button variant="outline" size="icon" asChild className="h-9 w-9">
                        <Link href={routeTo("/shipments")}><ArrowLeft className="h-4 w-4" /></Link>
                    </Button>
                    <div>
                        <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-3">
                            {shipment.tracking_id || "Pending Tracking ID"}
                            <Badge variant="secondary">{shipment.status.replace("_", " ")}</Badge>
                        </h1>
                        <p className="text-slate-500 text-sm mt-1">Ref: {shipment.order_reference_id}</p>
                    </div>
                </div>

                <div className="flex gap-2">
                    <Button variant="outline" onClick={handlePrintLabel} disabled={isPrinting}>
                        {isPrinting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Printer className="mr-2 h-4 w-4" />}
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

            {/* 🔥 NEW: Dynamic Tracking Banner */}
            {shipment.tracking_id && (
                <div className="bg-primary rounded-2xl shadow-lg p-6 sm:p-8 flex flex-col sm:flex-row items-center justify-between gap-6 relative overflow-hidden">
                    {/* Decorative Background Icon */}
                    <div className="absolute -right-8 -top-8 opacity-10 pointer-events-none">
                        <PackageSearch className="w-48 h-48 text-white" />
                    </div>

                    <div className="flex flex-col sm:flex-row items-center sm:items-start gap-4 text-center sm:text-left relative z-10">
                        <div className="h-14 w-14 bg-white/20 rounded-full flex items-center justify-center shrink-0 backdrop-blur-sm">
                            <PackageSearch className="h-7 w-7 text-white" />
                        </div>
                        <div>
                            <h3 className="text-xl md:text-2xl font-bold text-white tracking-tight">Live Tracking Details</h3>
                            <p className="text-white/80 mt-1">View the public tracking page for real-time updates and shareable links.</p>
                        </div>
                    </div>

                    <Button variant="secondary" size="lg" asChild className="w-full sm:w-auto font-bold shadow-sm relative z-10 h-12 px-8 hover:scale-105 transition-transform duration-200">
                        <Link href={routeTo(`/track/${shipment.tracking_id}`)}>
                            Track Shipment <ArrowRight className="ml-2 h-5 w-5" />
                        </Link>
                    </Button>
                </div>
            )}

            {/* The Mobile-Responsive Layout Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                {/* ⬅️ LEFT COLUMN */}
                <div className="lg:col-span-2 space-y-6">
                    {/* Route Details Card */}
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                        <div className="flex items-center gap-2 mb-4">
                            <MapPin className="h-5 w-5 text-primary" />
                            <h3 className="text-lg font-semibold text-slate-900">Route Details</h3>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                            <div className="space-y-1">
                                <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Origin</p>
                                <p className="font-semibold text-slate-900">{shipment.pickup_address.name}</p>
                                <p className="text-sm text-slate-600 leading-relaxed">{shipment.pickup_address.address_line1}</p>
                                <p className="text-sm text-slate-600 leading-relaxed">
                                    {shipment.pickup_address.city}, {shipment.pickup_address.state} {shipment.pickup_address.pincode}
                                </p>
                                <p className="text-sm text-slate-500 mt-2">{shipment.pickup_address.phone}</p>
                            </div>
                            <div className="space-y-1">
                                <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Destination</p>
                                <p className="font-semibold text-slate-900">{shipment.delivery_address.name}</p>
                                <p className="text-sm text-slate-600 leading-relaxed">{shipment.delivery_address.address_line1}</p>
                                <p className="text-sm text-slate-600 leading-relaxed">
                                    {shipment.delivery_address.city}, {shipment.delivery_address.state} {shipment.delivery_address.pincode}
                                </p>
                                <p className="text-sm text-slate-500 mt-2">{shipment.delivery_address.phone}</p>
                            </div>
                        </div>
                    </div>

                    {/* The Audit Log Timeline */}
                    <AdminTimeline activities={timeline} />
                </div>

                {/* ➡️ RIGHT SIDEBAR: Packages */}
                <div className="space-y-6">
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col h-full lg:max-h-[800px]">
                        <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2 shrink-0">
                            <Box className="h-4 w-4 text-primary" />
                            <h3 className="font-semibold text-slate-900">Packages ({shipment.packages.length})</h3>
                        </div>
                        <div className="p-4 space-y-3 overflow-y-auto">
                            {shipment.packages.map((pkg, idx) => (
                                <div key={pkg.id || idx} className="p-3 bg-slate-50 rounded-lg border border-slate-100 space-y-2">
                                    <div className="flex justify-between items-start">
                                        <span className="text-sm font-semibold text-slate-900">Box {idx + 1}</span>
                                        <span className="text-sm font-medium text-slate-600">{pkg.weight} kg</span>
                                    </div>
                                    <div className="text-xs text-slate-500 flex justify-between">
                                        <span>{pkg.length} x {pkg.breadth} x {pkg.height} cm</span>
                                        {pkg.description && <span className="truncate ml-2 max-w-[100px]">{pkg.description}</span>}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

            </div>
        </div>
    );
}