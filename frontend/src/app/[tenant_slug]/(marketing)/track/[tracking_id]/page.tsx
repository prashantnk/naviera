// src/app/[tenant_slug]/(marketing)/track/[tracking_id]/page.tsx
"use client";

import { PublicTrackingRead, ShipmentsService } from "@/api_client";
import { TrackingTimeline } from "@/components/blocks/tracking-timeline";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Loader2, PackageSearch } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

export default function PublicTrackingPage() {
    const params = useParams();
    const trackingId = params.tracking_id as string;
    const { routeTo } = useTenant();

    const [data, setData] = useState<PublicTrackingRead | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!trackingId) return;

        const fetchTrackingData = async () => {
            try {
                // Because configureApiClient is called in TenantProvider globally, 
                // we can instantly call our API without setting headers manually!
                const response = await ShipmentsService.trackShipment(trackingId);
                setData(response);
            } catch (err: any) {
                console.error("Tracking Error:", err);
                setError("We couldn't find a shipment with that Tracking ID.");
            } finally {
                setLoading(false);
            }
        };

        fetchTrackingData();
    }, [trackingId]);

    return (
        <div className="min-h-[calc(100vh-64px)] bg-slate-50/50 py-12 px-4 md:px-6">
            <div className="container mx-auto max-w-4xl space-y-8">

                {/* Page Header */}
                <div className="text-center space-y-2">
                    <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Track Your Shipment</h1>
                    <p className="text-slate-500">Real-time status updates for your delivery.</p>
                </div>

                {/* State Management */}
                {loading && (
                    <div className="flex flex-col items-center justify-center h-64 space-y-4">
                        <Loader2 className="h-8 w-8 animate-spin text-primary" />
                        <p className="text-slate-500">Locating your package...</p>
                    </div>
                )}

                {error && (
                    <div className="bg-white border border-slate-200 rounded-xl p-8 text-center space-y-4 max-w-md mx-auto shadow-sm">
                        <div className="mx-auto w-12 h-12 bg-red-50 rounded-full flex items-center justify-center mb-4">
                            <PackageSearch className="h-6 w-6 text-red-500" />
                        </div>
                        <h3 className="text-lg font-bold text-slate-900">Shipment Not Found</h3>
                        <p className="text-slate-500">{error}</p>
                        <Button asChild className="mt-4">
                            <Link href={routeTo("/")}>Return Home</Link>
                        </Button>
                    </div>
                )}

                {/* Success State */}
                {data && !loading && !error && (
                    <TrackingTimeline data={data} />
                )}

            </div>
        </div>
    );
}