// frontend/src/app/[tenant_slug]/(auth)/login/login-form.tsx
"use client";

import { useTenant } from '@/components/providers/tenant-provider';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getSupabaseClient } from "@/lib/supabase";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export function LoginForm() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { tenantSlug, routeTo } = useTenant();
    const supabase = getSupabaseClient(tenantSlug);

    // 🔥 NEW: Extract the 'next' intent
    const nextUrl = searchParams.get("next") || "/dashboard";

    const [step, setStep] = useState<1 | 2>(1);
    const [email, setEmail] = useState("");
    const [otp, setOtp] = useState("");
    const [loading, setLoading] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    useEffect(() => {
        const checkSession = async () => {
            const { data: { session } } = await supabase.auth.getSession();
            if (session) {
                // Instantly bounce authenticated users to their intended destination!
                router.replace(routeTo(nextUrl));
            }
        };
        checkSession();
    }, [supabase, router, routeTo, nextUrl]);

    // --- METHOD 1: GOOGLE OAUTH ---
    const handleOAuthLogin = async (provider: 'google') => {
        setLoading(provider);
        setError(null);
        try {
            const origin = window.location.origin;
            // 🔥 NEW: Pass the nextUrl into the OAuth callback so it remembers!
            const callbackUrl = `${origin}${routeTo('/callback')}?next=${encodeURIComponent(nextUrl)}`;
            const { error: authError } = await supabase.auth.signInWithOAuth({
                provider,
                options: { redirectTo: callbackUrl },
            });
            if (authError) throw new Error(authError.message);
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Failed to sign in with OAuth");
            setLoading(null);
        }
    };

    // --- METHOD 2, STEP 1: SEND OTP ---
    const handleSendOtp = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading('email');
        setError(null);
        setSuccess(null);

        try {
            const { error: authError } = await supabase.auth.signInWithOtp({ email });
            if (authError) throw new Error(authError.message);
            setStep(2);
            setSuccess("We sent a 6-digit code to your email. Please enter it below.");
        } catch (err: unknown) {
            console.error(err);
            setError(err instanceof Error ? err.message : "Failed to send OTP. Please try again.");
        } finally {
            setLoading(null);
        }
    };

    // --- METHOD 2, STEP 2: VERIFY OTP & SYNC BACKEND ---
    const handleVerifyOtp = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading('verify');
        setError(null);

        try {
            const { data: authData, error: verifyError } = await supabase.auth.verifyOtp({ email, token: otp, type: 'email' });
            if (verifyError) throw new Error("Invalid or expired code. Please try again.");
            if (!authData.session) throw new Error("No session returned");

            const jwt = authData.session.access_token;
            const res = await fetch("/api/v1/users/onboard", {
                method: "POST",
                headers: { "Authorization": `Bearer ${jwt}`, "X-Tenant-Slug": tenantSlug },
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Failed to sync user with backend");
            }

            // 🔥 NEW: Redirect to intended destination instead of hardcoded dashboard
            router.push(routeTo(nextUrl));

        } catch (err: unknown) {
            console.error(err);
            setError(err instanceof Error ? err.message : "Failed to verify OTP and sync user with backend");
        } finally {
            setLoading(null);
        }
    };

    return (
        <div className="space-y-6">
            {error && (
                <div className="p-3 text-sm text-red-500 bg-red-50 rounded-md border border-red-200">
                    {error}
                </div>
            )}
            {success && (
                <div className="p-3 text-sm text-green-700 bg-green-50 rounded-md border border-green-200">
                    {success}
                </div>
            )}

            {step === 1 && (
                <>
                    <form onSubmit={handleSendOtp} className="space-y-4">
                        <div className="space-y-2">
                            <Label htmlFor="email" className="text-slate-700">Email address</Label>
                            <Input
                                id="email"
                                type="email"
                                placeholder="name@company.com"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                className="bg-slate-50"
                            />
                        </div>
                        <Button type="submit" className="w-full text-md h-10" disabled={!!loading}>
                            {loading === 'email' ? "Sending code..." : "Continue with Email"}
                        </Button>
                    </form>

                    <div className="relative">
                        <div className="absolute inset-0 flex items-center">
                            <span className="w-full border-t border-slate-200" />
                        </div>
                        <div className="relative flex justify-center text-xs uppercase">
                            <span className="bg-white px-2 text-slate-500">Or continue with</span>
                        </div>
                    </div>

                    <Button
                        type="button"
                        variant="outline"
                        className="w-full text-md h-12 bg-white"
                        onClick={() => handleOAuthLogin('google')}
                        disabled={!!loading}
                    >
                        <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
                            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                        </svg>
                        {loading === 'google' ? "Connecting..." : "Sign in with Google"}
                    </Button>
                </>
            )}

            {step === 2 && (
                <form onSubmit={handleVerifyOtp} className="space-y-4">
                    <div className="space-y-2">
                        <Label htmlFor="otp" className="text-slate-700">Verification Code</Label>
                        <Input
                            id="otp"
                            type="text"
                            placeholder="123456"
                            value={otp}
                            onChange={(e) => setOtp(e.target.value)}
                            required
                            className="bg-slate-50 text-center tracking-widest text-lg"
                            maxLength={6}
                        />
                    </div>
                    <Button type="submit" className="w-full text-md h-10" disabled={!!loading}>
                        {loading === 'verify' ? "Verifying..." : "Verify & Sign In"}
                    </Button>

                    <div className="text-center mt-4">
                        <button
                            type="button"
                            onClick={() => { setStep(1); setSuccess(null); setError(null); setOtp(""); }}
                            className="text-sm text-slate-500 hover:text-primary transition-colors"
                        >
                            Use a different email
                        </button>
                    </div>
                </form>
            )}
        </div>
    );
}