// frontend/src/app/[tenant_slug]/(auth)/callback/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase";
import { Loader2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

// 🔥 Extract logic into a Handler to support Suspense
function CallbackHandler() {
    const router = useRouter();
    const params = useParams();
    const searchParams = useSearchParams();
    
    const tenantSlug = params.tenant_slug as string;
    const { routeTo } = useTenant();
    
    // 🔥 NEW: Read the 'next' parameter from the URL
    const nextUrl = searchParams.get("next") || "/dashboard";

    const [error, setError] = useState<string | null>(null);
    const hasAttemptedSync = useRef(false);
    const supabase = getSupabaseClient(tenantSlug);

    useEffect(() => {
        if (hasAttemptedSync.current || !tenantSlug) return;
        hasAttemptedSync.current = true;

        const syncUserWithBackend = async () => {
            try {
                const { data: { session }, error: sessionError } = await supabase.auth.getSession();

                if (sessionError) throw sessionError;
                if (!session) throw new Error("No secure session found. Please try logging in again.");

                const jwt = session.access_token;

                const res = await fetch("/api/v1/users/onboard", {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${jwt}`,
                        "X-Tenant-Slug": tenantSlug,
                    },
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || "Failed to sync user with backend");
                }

                // 🔥 NEW: Push the user back to where they came from!
                router.push(routeTo(nextUrl));

            } catch (err: any) {
                console.error("Auth sync error:", err);
                setError(err.message);
            }
        };

        syncUserWithBackend();
    }, [router, tenantSlug, routeTo, supabase, nextUrl]);

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center p-8 text-center space-y-4 max-w-md bg-white rounded-xl shadow-sm border">
                <h2 className="text-xl font-bold text-red-600">Authentication Error</h2>
                <p className="text-slate-600">{error}</p>
                <Button onClick={() => router.push(routeTo(`/login`))}>Return to Login</Button>
            </div>
        );
    }

    return (
        <div className="flex flex-col items-center justify-center space-y-4">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
            <h2 className="text-xl font-semibold text-slate-700">Securing your session...</h2>
            <p className="text-sm text-slate-500">Please wait while we log you into {tenantSlug}.</p>
        </div>
    );
}

// Wrap it in Suspense!
export default function AuthCallbackPage() {
    return (
        <Suspense fallback={<div className="flex justify-center p-8"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}>
            <CallbackHandler />
        </Suspense>
    );
}