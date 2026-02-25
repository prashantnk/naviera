// src/app/[tenant_slug]/(app)/shipments/page.tsx
"use client";

import { PickupRead, ShipmentsService } from "@/api_client";
import { DataTable } from "@/components/ui/data-table";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { columns } from "./columns";

export default function ShipmentsPage() {
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
        <div className="space-y-6 max-w-6xl mx-auto">
            <div>
                <h1 className="text-3xl font-bold text-slate-900">Shipments</h1>
                <p className="text-slate-500 mt-1">Manage and track all your deliveries.</p>
            </div>

            {error && (
                <div className="p-4 text-red-600 bg-red-50 rounded-md border border-red-200">
                    Error: {error}
                </div>
            )}

            {loading ? (
                <div className="flex h-64 items-center justify-center border rounded-md bg-white border-dashed">
                    <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
                </div>
            ) : (
                <DataTable columns={columns} data={data} />
            )}
        </div>
    );
}