// src/app/[tenant_slug]/(marketing)/track/page.tsx
"use client";

import {
    TRACKING_INPUT_PLACEHOLDER,
    normalizeTrackingId,
} from "@/components/blocks/tracking-display";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PackageSearch } from "lucide-react";
import { useProgressRouter } from "@/hooks/use-progress-router";
import { useState } from "react";

export default function TrackIndexPage() {
    const [trackingId, setTrackingId] = useState("");
    const router = useProgressRouter();
    const { routeTo } = useTenant();

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const normalized = normalizeTrackingId(trackingId);
        if (normalized) {
            router.push(routeTo(`/track/${encodeURIComponent(normalized)}`));
        }
    };

    return (
        <div className="bg-slate-50/50 flex flex-col items-center justify-center py-24 px-4">
            <div className="max-w-xl w-full bg-white rounded-2xl shadow-xl p-8 md:p-12 space-y-8 text-center border border-slate-100">

                <div className="mx-auto w-20 h-20 bg-primary/10 rounded-full flex items-center justify-center mb-2">
                    <PackageSearch className="h-10 w-10 text-primary" />
                </div>

                <div className="space-y-3">
                    <h1 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight">Track your shipment</h1>
                    <p className="text-slate-500 text-lg">Enter your tracking or reference ID below to get real-time updates on your package.</p>
                </div>

                <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3 pt-4">
                    <Input
                        value={trackingId}
                        onChange={(e) => setTrackingId(e.target.value)}
                        placeholder={TRACKING_INPUT_PLACEHOLDER}
                        aria-label="AWB / tracking number"
                        autoCapitalize="characters"
                        className="h-14 text-lg bg-slate-50 px-4 uppercase placeholder:normal-case"
                        autoFocus
                    />
                    <Button type="submit" size="lg" className="h-14 px-8 text-lg font-semibold">
                        Track
                    </Button>
                </form>
            </div>
        </div>
    );
}