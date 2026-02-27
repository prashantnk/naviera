// frontend/src/app/[tenant_slug]/(marketing)/[...slug]/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Construction } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

export default function ComingSoonPage() {
    const { routeTo } = useTenant();
    const params = useParams();
    // Safely parse the slug path
    const pathArray = params.slug as string[];
    const pageName = pathArray ? pathArray.join("/").toUpperCase() : "PAGE";

    return (
        <div className="min-h-[60vh] flex flex-col items-center justify-center text-center px-4 space-y-6 bg-slate-50/50">
            <div className="h-20 w-20 bg-primary/10 rounded-full flex items-center justify-center">
                <Construction className="h-10 w-10 text-primary" />
            </div>
            <div>
                <h1 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight">
                    {pageName}
                </h1>
                <p className="text-lg text-slate-500 mt-2 max-w-md mx-auto">
                    We are currently building this section of the website. Check back soon for updates!
                </p>
            </div>
            <Button asChild size="lg" className="mt-4 rounded-full px-8">
                <Link href={routeTo("/")}>Return Home</Link>
            </Button>
        </div>
    );
}