// frontend/src/app/[tenant_slug]/(auth)/callback/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getSupabaseClient } from "@/lib/supabase";
import { sanitizeNextPath } from "@/lib/safe-redirect";
import { KeyRound, Loader2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import {
    consumePendingPasswordReset,
    MIN_PASSWORD_LENGTH,
    SET_PASSWORD_CALLBACK_INTENT,
} from "../login/login-form";

// 🔥 Extract logic into a Handler to support Suspense
function CallbackHandler() {
    const router = useRouter();
    const params = useParams();
    const searchParams = useSearchParams();
    
    const tenantSlug = params.tenant_slug as string;
    const { routeTo, tenant } = useTenant();
    // Show the courier's display name (e.g. "Logismart Shipping"), never the raw URL slug.
    const tenantDisplayName = tenant?.name || "your account";
    
    // 🔥 NEW: Read the 'next' parameter from the URL (sanitised against open redirects)
    const nextUrl = sanitizeNextPath(searchParams.get("next"));
    const intent = searchParams.get("intent");

    const [error, setError] = useState<string | null>(null);
    const [needsPasswordPrompt, setNeedsPasswordPrompt] = useState(false);
    const [newPassword, setNewPassword] = useState("");
    const [passwordError, setPasswordError] = useState<string | null>(null);
    const [savingPassword, setSavingPassword] = useState(false);
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

                // If the user started "Set / Forgot Password" in this browser tab,
                // apply their chosen password before redirecting.
                const pendingPassword = consumePendingPasswordReset(session.user?.email);
                if (pendingPassword) {
                    const { error: updateError } = await supabase.auth.updateUser({
                        password: pendingPassword,
                    });
                    if (updateError) throw updateError;
                    router.push(routeTo(nextUrl));
                    return;
                }

                // If the user opened the Set/Forgot Password magic link in a new tab
                // (where sessionStorage from the login tab is empty), prompt for their
                // new password before completing redirect.
                if (intent === SET_PASSWORD_CALLBACK_INTENT) {
                    setNeedsPasswordPrompt(true);
                    return;
                }

                // 🔥 NEW: Push the user back to where they came from!
                router.push(routeTo(nextUrl));

            } catch (err: unknown) {
                console.error("Auth sync error:", err);
                const errorObj = err as { message?: string };
                setError(errorObj.message || "Failed to sync session.");
            }
        };

        syncUserWithBackend();
    }, [router, tenantSlug, routeTo, supabase, nextUrl, intent]);

    const handleSavePassword = async (e: React.FormEvent) => {
        e.preventDefault();
        setPasswordError(null);

        if (newPassword.length < MIN_PASSWORD_LENGTH) {
            setPasswordError(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
            return;
        }

        setSavingPassword(true);
        try {
            const { error: updateError } = await supabase.auth.updateUser({
                password: newPassword,
            });
            if (updateError) {
                throw new Error(updateError.message);
            }
            router.push(routeTo(nextUrl));
        } catch (err: unknown) {
            setPasswordError(
                err instanceof Error ? err.message : "Failed to save new password."
            );
        } finally {
            setSavingPassword(false);
        }
    };

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center p-8 text-center space-y-4 max-w-md bg-card rounded-xl shadow-sm border">
                <h2 className="text-xl font-bold text-destructive">Authentication Error</h2>
                <p className="text-muted-foreground">{error}</p>
                <Button onClick={() => router.push(routeTo(`/login`))}>Return to Login</Button>
            </div>
        );
    }

    if (needsPasswordPrompt) {
        return (
            <form
                onSubmit={handleSavePassword}
                data-testid="callback.set-password-form"
                className="flex flex-col p-8 space-y-4 w-full max-w-md bg-card rounded-xl shadow-sm border"
            >
                <div className="flex items-center gap-2">
                    <KeyRound className="h-5 w-5 text-primary" />
                    <h2 className="text-xl font-bold text-foreground">Set your new password</h2>
                </div>
                <p className="text-sm text-muted-foreground">
                    Your email link has been verified for {tenantDisplayName}. Enter your new password to finish signing in.
                </p>
                {passwordError && (
                    <div
                        role="alert"
                        className="p-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg"
                    >
                        {passwordError}
                    </div>
                )}
                <div className="space-y-1.5">
                    <Label htmlFor="callback-new-password">
                        New password (min. {MIN_PASSWORD_LENGTH} characters)
                    </Label>
                    <Input
                        id="callback-new-password"
                        type="password"
                        required
                        minLength={MIN_PASSWORD_LENGTH}
                        placeholder="••••••••"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        disabled={savingPassword}
                        autoComplete="new-password"
                    />
                </div>
                <Button type="submit" className="w-full font-semibold" disabled={savingPassword}>
                    {savingPassword ? "Saving password..." : "Save Password & Continue"}
                </Button>
            </form>
        );
    }

    return (
        <div className="flex flex-col items-center justify-center space-y-4">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
            <h2 className="text-xl font-semibold text-foreground">Securing your session</h2>
            <p className="text-sm text-muted-foreground">Please wait while we sign you in to {tenantDisplayName}.</p>
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