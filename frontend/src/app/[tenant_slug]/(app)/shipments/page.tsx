// src/app/[tenant_slug]/(app)/shipments/page.tsx
"use client";

import { PickupRead, ShipmentsService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { ArrowRight, Loader2, MapPin, PackageSearch } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { columns } from "./columns";

export default function ShipmentsPage() {
    const router = useRouter();
    const { routeTo } = useTenant();
    const [data, setData] = useState<PickupRead[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchShipments = async () => {
            try {
                const response = await ShipmentsService.listShipments(1, 50);
                setData(response.items);
            } catch (err: any) {
                console.error(err);
                setError(err.message || "Failed to fetch shipments.");
            } finally {
                setLoading(false);
            }
        };

        fetchShipments();
    }, []);

    return (
        <div className="space-y-8 max-w-6xl mx-auto pb-12">
            <div>
                <h1 className="text-3xl font-bold text-slate-900">Shipments</h1>
                <p className="text-slate-500 mt-1">Manage and track all your deliveries.</p>
            </div>

            {/* 🔥 NEW: Customer-Friendly Tracking Banner */}
            <div className="bg-slate-900 rounded-2xl p-6 md:p-8 shadow-xl flex flex-col md:flex-row items-center justify-between gap-6 relative overflow-hidden">
                {/* Decorative Icon */}
                <div className="absolute right-0 top-0 opacity-5 pointer-events-none transform translate-x-1/4 -translate-y-1/4">
                    <PackageSearch className="h-64 w-64 text-white" />
                </div>

                <div className="flex flex-col md:flex-row items-center md:items-start gap-4 text-center md:text-left relative z-10">
                    <div className="h-14 w-14 bg-primary/20 rounded-full flex items-center justify-center shrink-0">
                        <MapPin className="h-7 w-7 text-primary" />
                    </div>
                    <div>
                        <h2 className="text-xl md:text-2xl font-bold text-white tracking-tight">Need to track a specific package?</h2>
                        <p className="text-slate-400 mt-1 text-sm md:text-base max-w-xl">Use our public portal to get real-time location and status updates instantly. No login required.</p>
                    </div>
                </div>

                <div className="w-full md:w-auto relative z-10">
                    <Button size="lg" asChild className="w-full md:w-auto shadow-md text-md px-8 h-12">
                        <Link href={routeTo("/track")}>
                            Open Tracker <ArrowRight className="ml-2 h-5 w-5" />
                        </Link>
                    </Button>
                </div>
            </div>

            {error && (
                <div className="p-4 text-red-600 bg-red-50 rounded-md border border-red-200">
                    Error: {error}
                </div>
            )}

            {loading ? (
                <div className="flex h-64 items-center justify-center border rounded-xl bg-white border-dashed">
                    <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
                </div>
            ) : (
                <DataTable
                    columns={columns}
                    data={data}
                    onRowClick={(row) => router.push(routeTo(`/shipments/${row.id}`))}
                />
            )}
        </div>
    );
}