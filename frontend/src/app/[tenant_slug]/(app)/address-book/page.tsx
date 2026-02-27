// src/app/[tenant_slug]/(app)/address-book/page.tsx
"use client";

import { AddressRead, AddressesService } from "@/api_client";
import { AddAddressDialog } from "@/components/forms/add-address-dialog"; // <-- IMPORT NEW MODAL
import { DataTable } from "@/components/ui/data-table";
import { Loader2, MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { columns } from "./columns";

export default function AddressBookPage() {
    const [data, setData] = useState<AddressRead[]>([]);
    const [loading, setLoading] = useState(true);

    const fetchAddresses = async () => {
        try {
            const response = await AddressesService.listSavedAddresses();
            setData(response);
        } catch (err) {
            console.error("Failed to fetch addresses:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAddresses();
    }, []);

    return (
        <div className="space-y-6 max-w-6xl mx-auto">
            {/* Header Section */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Address Book</h1>
                    <p className="text-slate-500 mt-1">Manage your saved warehouses and customer addresses.</p>
                </div>

                {/* 🔥 INJECT THE SMART MODAL HERE */}
                <AddAddressDialog onSuccess={fetchAddresses} />
            </div>

            {/* Data Grid Section */}
            {loading ? (
                <div className="flex h-64 items-center justify-center border rounded-xl bg-white shadow-sm">
                    <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
                </div>
            ) : data.length === 0 ? (
                <div className="flex flex-col h-64 items-center justify-center border rounded-xl bg-white shadow-sm space-y-3">
                    <div className="h-12 w-12 bg-slate-50 rounded-full flex items-center justify-center">
                        <MapPin className="h-6 w-6 text-slate-400" />
                    </div>
                    <p className="text-slate-500 font-medium">No saved addresses yet.</p>
                </div>
            ) : (
                <DataTable columns={columns} data={data} />
            )}
        </div>
    );
}