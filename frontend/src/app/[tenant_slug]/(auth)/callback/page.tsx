// src/app/[tenant_slug]/(auth)/callback/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase";
import { Loader2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export default function AuthCallbackPage() {
    const router = useRouter();

    // Teacher's Note: In Client Components in Next.js 15, we use the `useParams` hook 
    // to safely extract the dynamic folder names from the URL.
    const params = useParams();
    const tenantSlug = params.tenant_slug as string;
    const { routeTo } = useTenant();

    const [error, setError] = useState<string | null>(null);

    // React 18+ runs useEffect twice in development mode. 
    // We use a ref to ensure we only call our backend API once.
    const hasAttemptedSync = useRef(false);
    const supabase = getSupabaseClient(tenantSlug);

    useEffect(() => {
        if (hasAttemptedSync.current || !tenantSlug) return;
        hasAttemptedSync.current = true;

        const syncUserWithBackend = async () => {
            try {
                // 1. Supabase JS automatically parses the hidden tokens in the URL 
                // that Google sent back and establishes a secure local session.
                const { data: { session }, error: sessionError } = await supabase.auth.getSession();

                if (sessionError) throw sessionError;
                if (!session) throw new Error("No secure session found. Please try logging in again.");

                const jwt = session.access_token;

                // 2. Just-In-Time (JIT) Provisioning
                // Send the secure token to our FastAPI backend to create/sync the user profile
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

                // 3. Success! Unlock the gates and send them to the App Zone
                router.push(routeTo(`/dashboard`));

            } catch (err: any) {
                console.error("Auth sync error:", err);
                setError(err.message);
            }
        };

        syncUserWithBackend();
    }, [router, tenantSlug, routeTo]);

    // --- UI State ---
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