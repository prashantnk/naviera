// src/components/auth/auth-guard.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { getSupabaseClient } from "@/lib/supabase";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function AuthGuard({ children }: { children: React.ReactNode }) {
    const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
    const router = useRouter();
    const { routeTo, tenantSlug } = useTenant();
    const supabase = getSupabaseClient(tenantSlug);

    useEffect(() => {
        const checkAuth = async () => {
            // Check local storage for an active Supabase session
            const { data: { session } } = await supabase.auth.getSession();

            if (!session) {
                // Not logged in? Kick them to their specific tenant's login page!
                router.push(routeTo("/login"));
            } else {
                setIsAuthenticated(true);
            }
        };

        checkAuth();
    }, [router, routeTo]);

    // While checking, show a full-screen loading state themed to the tenant
    if (isAuthenticated === null) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-slate-50">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
            </div>
        );
    }

    // If authenticated, render the dashboard content!
    return <>{children}</>;
}