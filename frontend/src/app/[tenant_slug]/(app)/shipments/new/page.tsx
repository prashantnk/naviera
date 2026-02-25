// src/app/[tenant_slug]/(app)/shipments/new/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { ArrowLeft, PackagePlus } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner"; // <-- Ready for action!

export default function CreateShipmentDummyPage() {
    const { routeTo } = useTenant();

    return (
        <div className="max-w-4xl mx-auto space-y-6">

            {/* Header with Back Button */}
            <div className="flex items-center gap-4">
                <Button variant="outline" size="icon" asChild className="h-9 w-9">
                    <Link href={routeTo("/shipments")}>
                        <ArrowLeft className="h-4 w-4" />
                    </Link>
                </Button>
                <div>
                    <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Create Booking</h1>
                    <p className="text-slate-500 mt-1">Fill out the details below to schedule a new pickup.</p>
                </div>
            </div>

            {/* The Dummy Form Container */}
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-8 md:p-16 flex flex-col items-center justify-center text-center space-y-6 mt-8">
                <div className="h-20 w-20 bg-primary/10 rounded-full flex items-center justify-center">
                    <PackagePlus className="h-10 w-10 text-primary" />
                </div>

                <div className="max-w-md space-y-2">
                    <h3 className="text-xl font-bold text-slate-900">Multi-Step Form Goes Here</h3>
                    <p className="text-slate-500 text-sm leading-relaxed">
                        In the next phase, we will implement React Hook Form and Zod to build a strict,
                        enterprise-grade multi-step wizard (Addresses → Packages → Documents).
                    </p>
                </div>

                <div className="flex gap-4 pt-4">
                    <Button variant="outline" onClick={() => toast.info("Draft saved to local storage!")}>
                        Save as Draft
                    </Button>
                    <Button onClick={() => toast.success("This will trigger the POST API later!")}>
                        Simulate Submission
                    </Button>
                </div>
            </div>

        </div>
    );
}