// src/app/[tenant_slug]/(app)/shipments/[id]/page.tsx
"use client";

import { PickupRead, ShipmentsService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { UpdateStatusDialog } from "@/components/forms/update-status-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Box, Loader2, MapPin } from "lucide-react";
import Link from "next/link";

export default function ShipmentDetailsPage() {
    const params = useParams();
    const shipmentId = params.id as string;
    const { routeTo } = useTenant();

    const [shipment, setShipment] = useState<PickupRead | null>(null);
    const [loading, setLoading] = useState(true);

    const fetchDetails = async () => {
        if (!shipmentId) return;
        try {
            const data = await ShipmentsService.getShipmentDetails(shipmentId);
            setShipment(data);
        } catch (error) {
            console.error("Failed to fetch shipment details:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchDetails();
    }, [shipmentId]);

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
                            <Badge variant="secondary">{shipment.status}</Badge>
                        </h1>
                        <p className="text-slate-500 text-sm mt-1">Ref: {shipment.order_reference_id}</p>
                    </div>
                </div>

                {/* Admin Operations Placeholder */}
                <div className="flex gap-2">
                    <UpdateStatusDialog
                        shipmentId={shipment.id}
                        currentStatus={shipment.status}
                        onSuccess={fetchDetails}
                    />
                </div>
            </div>

            {/* Layout Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

                {/* Left Column: Addresses */}
                <div className="md:col-span-2 space-y-6">
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                        <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2 mb-4">
                            <MapPin className="h-5 w-5 text-primary" /> Route Details
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
                            <div>
                                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Origin</p>
                                <p className="font-medium text-slate-900">{shipment.pickup_address.name}</p>
                                <p className="text-sm text-slate-600 mt-1">{shipment.pickup_address.address_line1}</p>
                                <p className="text-sm text-slate-600">{shipment.pickup_address.city}, {shipment.pickup_address.state} {shipment.pickup_address.pincode}</p>
                                <p className="text-sm text-slate-500 mt-2">{shipment.pickup_address.phone}</p>
                            </div>
                            <div>
                                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Destination</p>
                                <p className="font-medium text-slate-900">{shipment.delivery_address.name}</p>
                                <p className="text-sm text-slate-600 mt-1">{shipment.delivery_address.address_line1}</p>
                                <p className="text-sm text-slate-600">{shipment.delivery_address.city}, {shipment.delivery_address.state} {shipment.delivery_address.pincode}</p>
                                <p className="text-sm text-slate-500 mt-2">{shipment.delivery_address.phone}</p>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Column: Packages */}
                <div className="space-y-6">
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                        <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2 mb-4">
                            <Box className="h-5 w-5 text-primary" /> Packages ({shipment.packages.length})
                        </h3>
                        <div className="space-y-4">
                            {shipment.packages.map((pkg, i) => (
                                <div key={pkg.id} className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                                    <p className="text-sm font-medium text-slate-900">Box {i + 1}</p>
                                    <div className="flex justify-between text-sm text-slate-500 mt-1">
                                        <span>{pkg.length} x {pkg.breadth} x {pkg.height} cm</span>
                                        <span className="font-medium text-slate-700">{pkg.weight} kg</span>
                                    </div>
                                    {pkg.description && <p className="text-xs text-slate-400 mt-2 italic">{pkg.description}</p>}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

            </div>
        </div>
    );
}