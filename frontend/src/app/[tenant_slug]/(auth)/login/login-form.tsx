// frontend/src/app/[tenant_slug]/(auth)/login/login-form.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LEGAL_PATHS } from "@/lib/legal";
import { sanitizeNextPath } from "@/lib/safe-redirect";
import { getSupabaseClient, resetSupabaseClient } from "@/lib/supabase";
import { extractApiErrorMessage } from "@/lib/utils";
import { Eye, EyeOff, KeyRound, Mail, UserPlus } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { z } from "zod";

type AuthMethod = "password" | "otp";
type PasswordFlowMode = "signin" | "signup" | "set_password";

export const MIN_PASSWORD_LENGTH = 8;
export const signupPasswordSchema = z
  .string()
  .min(
    MIN_PASSWORD_LENGTH,
    `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`
  );
const resetPasswordSchema = z
  .string()
  .min(
    MIN_PASSWORD_LENGTH,
    `New password must be at least ${MIN_PASSWORD_LENGTH} characters.`
  );
/** `/auth/signup` returns 409 when the email already has an account (any tenant). */
const HTTP_CONFLICT = 409;
/** `/users/me` answers that make a stored session useless (bad token / not in tenant). */
const STALE_SESSION_STATUSES: ReadonlySet<number> = new Set([401, 403]);
/** Shown when "Create Account" is pressed without the consent checkbox (C-08). */
export const SIGNUP_CONSENT_REQUIRED_MESSAGE =
  "Please accept the Terms and Privacy Policy, and confirm you will not ship prohibited items.";
/**
 * Supabase error code when an OTP is requested for an unknown email with
 * `shouldCreateUser: false`. OTP never creates accounts: new users must go
 * through "Create Account", which records their Terms consent (C-08).
 */
const SUPABASE_OTP_SIGNUP_DISABLED_CODE = "otp_disabled";
/** Same condition on GoTrue versions that send no error code. */
const SUPABASE_OTP_SIGNUP_DISABLED_TEXT = /signups not allowed/i;
/** Shown instead of Supabase's raw "Signups not allowed for otp". */
export const OTP_NO_ACCOUNT_MESSAGE =
  "No account found for this email. Use Create Account to sign up.";
/** Session-storage key holding a pending password for the Set/Reset Password flow. */
export const PENDING_PASSWORD_RESET_KEY = "naviera_pending_password_reset";
/** Query param value passed to `/callback` when a magic link comes from Set/Reset Password. */
export const SET_PASSWORD_CALLBACK_INTENT = "set_password";

export interface PendingPasswordReset {
  email: string;
  password: string;
}

/**
 * Stores the user's chosen password in `sessionStorage` so that clicking the
 * magic link in the same browser tab applies it automatically on `/callback`.
 *
 * @param email - The user's email address.
 * @param password - The validated new password (>= 8 characters).
 */
export function savePendingPasswordReset(email: string, password: string): void {
  if (typeof window === "undefined") return;
  try {
    const payload: PendingPasswordReset = {
      email: email.trim().toLowerCase(),
      password,
    };
    window.sessionStorage.setItem(
      PENDING_PASSWORD_RESET_KEY,
      JSON.stringify(payload)
    );
  } catch {
    // Ignore storage quota / privacy mode errors; `/callback?intent=set_password` falls back to a prompt.
  }
}

/**
 * Reads and removes a pending password reset from `sessionStorage` if it matches
 * the authenticated user's email.
 *
 * @param sessionEmail - Email on the verified Supabase session.
 * @returns The pending password if present and matching, else `null`.
 */
export function consumePendingPasswordReset(
  sessionEmail?: string | null
): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PENDING_PASSWORD_RESET_KEY);
    window.sessionStorage.removeItem(PENDING_PASSWORD_RESET_KEY);
    if (!raw || !sessionEmail) return null;
    const parsed = JSON.parse(raw) as Partial<PendingPasswordReset>;
    if (
      typeof parsed.email === "string" &&
      typeof parsed.password === "string" &&
      parsed.email.trim().toLowerCase() === sessionEmail.trim().toLowerCase() &&
      parsed.password.length >= MIN_PASSWORD_LENGTH
    ) {
      return parsed.password;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Clears any stored pending password reset from `sessionStorage`.
 */
export function clearPendingPasswordReset(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(PENDING_PASSWORD_RESET_KEY);
  } catch {
    // Ignore storage errors
  }
}

/**
 * Turns a Supabase `signInWithOtp` error into user-facing copy.
 *
 * @param otpError - The `error` returned by `supabase.auth.signInWithOtp`.
 * @returns Friendly text for an unknown email, else Supabase's message.
 */
export function otpRequestErrorMessage(otpError: { code?: string; message: string }): string {
  const isUnknownEmail =
    otpError.code === SUPABASE_OTP_SIGNUP_DISABLED_CODE ||
    SUPABASE_OTP_SIGNUP_DISABLED_TEXT.test(otpError.message);
  return isUnknownEmail ? OTP_NO_ACCOUNT_MESSAGE : otpError.message;
}

interface PasswordAuthApiPayload {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  expires_at: number;
  supabase_user_id: string;
  user: {
    id: string;
    email: string;
    full_name?: string | null;
    role: string;
  };
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { tenantSlug, routeTo, tenant } = useTenant();
  const supabase = getSupabaseClient(tenantSlug);

  // Extract the 'next' intent (sanitised to block open redirects and marketing loops)
  const rawNext = sanitizeNextPath(searchParams.get("next"));
  const marketingOrAuthPaths = [
    "/",
    "/login",
    "/about",
    "/services",
    "/contact",
    `/${tenantSlug}`,
    `/${tenantSlug}/`,
    `/${tenantSlug}/login`,
    `/${tenantSlug}/about`,
    `/${tenantSlug}/services`,
    `/${tenantSlug}/contact`,
  ];
  const nextUrl = marketingOrAuthPaths.includes(rawNext) ? "/dashboard" : rawNext;

  const [authMethod, setAuthMethod] = useState<AuthMethod>("password");
  const [passwordMode, setPasswordMode] = useState<PasswordFlowMode>("signin");
  const [step, setStep] = useState<1 | 2>(1);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [otp, setOtp] = useState("");

  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [accountExists, setAccountExists] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);

  const isOAuthEnabled = tenant?.settings?.oAuthSignInEnabled === true || false;

  useEffect(() => {
    const checkSession = async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) return;

      try {
        const res = await fetch("/api/v1/users/me", {
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "X-Tenant-Slug": tenantSlug,
          },
        });
        if (res.ok) {
          router.replace(routeTo(nextUrl));
        } else if (STALE_SESSION_STATUSES.has(res.status)) {
          // Token rejected or not a member of this tenant: start clean. A 5xx keeps the
          // session so a backend restart does not log the user out.
          const backendMinted =
            typeof session.refresh_token === "string" &&
            session.refresh_token.startsWith("naviera-rt-");
          window.localStorage.removeItem(`sb-${tenantSlug}-auth-token`);
          resetSupabaseClient(tenantSlug);
          if (!backendMinted) {
            await supabase.auth.signOut().catch(() => {});
          }
        }
      } catch {
        // Keep user on login screen if backend verification fails
      }
    };
    void checkSession();
  }, [supabase, router, routeTo, nextUrl, tenantSlug]);

  const syncUserWithBackend = async (jwt: string) => {
    const res = await fetch("/api/v1/users/onboard", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "X-Tenant-Slug": tenantSlug,
      },
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(
        extractApiErrorMessage({ body: errData }, "Failed to sync user with backend")
      );
    }
  };

  const persistBackendPasswordSession = (data: PasswordAuthApiPayload) => {
    const sessionRecord = {
      access_token: data.access_token,
      token_type: data.token_type || "bearer",
      expires_in: data.expires_in,
      expires_at: data.expires_at,
      refresh_token: data.refresh_token,
      user: {
        id: data.supabase_user_id,
        aud: "authenticated",
        role: "authenticated",
        email: data.user.email,
      },
    };
    window.localStorage.setItem(
      `sb-${tenantSlug}-auth-token`,
      JSON.stringify(sessionRecord)
    );
    resetSupabaseClient(tenantSlug);
  };

  const resetMessagesAndStep = (
    newMethod?: AuthMethod,
    newPasswordMode?: PasswordFlowMode
  ) => {
    if (newMethod) setAuthMethod(newMethod);
    if (newPasswordMode) setPasswordMode(newPasswordMode);
    clearPendingPasswordReset();
    setStep(1);
    setOtp("");
    setError(null);
    setSuccess(null);
    setAccountExists(false);
  };

  // --- METHOD 1: GOOGLE OAUTH ---
  const handleOAuthLogin = async (provider: "google") => {
    setLoading(provider);
    setError(null);
    try {
      const origin = window.location.origin;
      const callbackUrl = `${origin}${routeTo(
        "/callback"
      )}?next=${encodeURIComponent(nextUrl)}`;
      const { error: authError } = await supabase.auth.signInWithOAuth({
        provider,
        options: { redirectTo: callbackUrl },
      });
      if (authError) throw new Error(authError.message);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to sign in with OAuth"
      );
      setLoading(null);
    }
  };

  // --- METHOD 2A: SIGN IN WITH EMAIL & PASSWORD ---
  const handlePasswordSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading("password-signin");
    setError(null);
    setSuccess(null);

    try {
      const res = await fetch("/api/v1/users/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Slug": tenantSlug,
        },
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(
          typeof errData.detail === "string"
            ? errData.detail
            : "Invalid email or password. If you are new here, click the 'Create Account' tab above."
        );
      }

      const data = (await res.json()) as PasswordAuthApiPayload;
      await persistBackendPasswordSession(data);
      router.push(routeTo(nextUrl));
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to sign in with password."
      );
    } finally {
      setLoading(null);
    }
  };

  // --- METHOD 2B: CREATE ACCOUNT WITH EMAIL & PASSWORD ---
  const handlePasswordSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading("password-signup");
    setError(null);
    setSuccess(null);
    setAccountExists(false);

    const parsedPassword = signupPasswordSchema.safeParse(password);
    if (!parsedPassword.success) {
      setError(parsedPassword.error.issues[0].message);
      setLoading(null);
      return;
    }

    if (!termsAccepted) {
      setError(SIGNUP_CONSENT_REQUIRED_MESSAGE);
      setLoading(null);
      return;
    }

    try {
      const res = await fetch("/api/v1/users/auth/signup", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Slug": tenantSlug,
        },
        body: JSON.stringify({
          email: email.trim(),
          password,
          full_name: fullName.trim() || undefined,
          terms_accepted: termsAccepted,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setAccountExists(res.status === HTTP_CONFLICT);
        throw new Error(
          extractApiErrorMessage({ body: errData }, "Failed to create account.")
        );
      }

      const data = (await res.json()) as PasswordAuthApiPayload;
      await persistBackendPasswordSession(data);
      router.push(routeTo(nextUrl));
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to create account."
      );
    } finally {
      setLoading(null);
    }
  };

  // --- METHOD 2C: SET / RESET PASSWORD FOR EXISTING OR OTP USERS ---
  const handleRequestPasswordOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading("set-password-otp");
    setError(null);
    setSuccess(null);

    const parsedPassword = resetPasswordSchema.safeParse(password);
    if (!parsedPassword.success) {
      setError(parsedPassword.error.issues[0].message);
      setLoading(null);
      return;
    }

    try {
      const origin = window.location.origin;
      const callbackUrl = `${origin}${routeTo(
        "/callback"
      )}?intent=${SET_PASSWORD_CALLBACK_INTENT}&next=${encodeURIComponent(nextUrl)}`;
      const { error: otpError } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: {
          emailRedirectTo: callbackUrl,
          // OTP signs in existing accounts only; sign-up (with consent) is "Create Account".
          shouldCreateUser: false,
          data: {
            tenant_name: tenant?.name || "Naviera Logistics",
          },
        },
      });
      if (otpError) throw new Error(otpRequestErrorMessage(otpError));

      savePendingPasswordReset(email, password);
      setStep(2);
      setSuccess(
        "We sent a 6-digit verification code to your email. Enter it below to set your password and sign in."
      );
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to send verification code."
      );
    } finally {
      setLoading(null);
    }
  };

  // --- METHOD 3, STEP 1: SEND PASSWORDLESS EMAIL OTP ---
  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading("email");
    setError(null);
    setSuccess(null);

    try {
      const origin = window.location.origin;
      const callbackUrl = `${origin}${routeTo(
        "/callback"
      )}?next=${encodeURIComponent(nextUrl)}`;
      const { error: authError } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: {
          emailRedirectTo: callbackUrl,
          // OTP signs in existing accounts only; sign-up (with consent) is "Create Account".
          shouldCreateUser: false,
          data: {
            tenant_name: tenant?.name || "Naviera Logistics",
          },
        },
      });
      if (authError) throw new Error(otpRequestErrorMessage(authError));
      setStep(2);
      setSuccess(
        "We sent a 6-digit code to your email. Please enter it below."
      );
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to send OTP. Please try again."
      );
    } finally {
      setLoading(null);
    }
  };

  // --- STEP 2: VERIFY OTP (FOR OTP LOGIN, SIGNUP CONFIRMATION, OR SETTING PASSWORD) ---
  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading("verify");
    setError(null);

    try {
      const cleanEmail = email.trim();
      const cleanToken = otp.trim();

      let verifyResult = await supabase.auth.verifyOtp({
        email: cleanEmail,
        token: cleanToken,
        type:
          authMethod === "password" && passwordMode === "signup"
            ? "signup"
            : "email",
      });

      if (verifyResult.error && authMethod === "password" && passwordMode === "signup") {
        verifyResult = await supabase.auth.verifyOtp({
          email: cleanEmail,
          token: cleanToken,
          type: "email",
        });
      }

      if (verifyResult.error) {
        throw new Error("Invalid or expired 6-digit code. Please try again.");
      }
      if (!verifyResult.data.session) {
        throw new Error("No session returned after verification.");
      }

      // If the user is in "set_password" mode, persist their new password onto their Supabase account now
      if (authMethod === "password" && passwordMode === "set_password") {
        const { error: updateError } = await supabase.auth.updateUser({
          password,
        });
        if (updateError) {
          throw new Error(updateError.message);
        }
        clearPendingPasswordReset();
      }

      await syncUserWithBackend(verifyResult.data.session.access_token);
      router.push(routeTo(nextUrl));
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to verify code and sync user with backend."
      );
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="space-y-5">
      {/* Top 3-Tab Switcher: Sign In | Create Account | Email OTP */}
      <div
        role="tablist"
        aria-label="Authentication mode"
        className="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1"
      >
        <button
          type="button"
          role="tab"
          data-testid="tab-signin"
          aria-selected={authMethod === "password" && passwordMode === "signin"}
          onClick={() => resetMessagesAndStep("password", "signin")}
          className={`flex items-center justify-center gap-1.5 rounded-md px-1 py-2 text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
            authMethod === "password" && passwordMode === "signin"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-600 hover:text-slate-900"
          }`}
        >
          <KeyRound className="hidden sm:block h-3.5 w-3.5" />
          Sign In
        </button>
        <button
          type="button"
          role="tab"
          data-testid="tab-signup"
          aria-selected={authMethod === "password" && passwordMode === "signup"}
          onClick={() => resetMessagesAndStep("password", "signup")}
          className={`flex items-center justify-center gap-1.5 rounded-md px-1 py-2 text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
            authMethod === "password" && passwordMode === "signup"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-600 hover:text-slate-900"
          }`}
        >
          <UserPlus className="hidden sm:block h-3.5 w-3.5" />
          Create Account
        </button>
        <button
          type="button"
          role="tab"
          data-testid="tab-otp"
          aria-selected={authMethod === "otp"}
          onClick={() => resetMessagesAndStep("otp")}
          className={`flex items-center justify-center gap-1.5 rounded-md px-1 py-2 text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
            authMethod === "otp"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-600 hover:text-slate-900"
          }`}
        >
          <Mail className="hidden sm:block h-3.5 w-3.5" />
          Email OTP
        </button>
      </div>

      {error && (
        <div className="p-3 text-sm text-red-600 bg-red-50 rounded-md border border-red-200">
          {error}
          {error === OTP_NO_ACCOUNT_MESSAGE && (
            <div className="mt-2 text-xs">
              <button
                type="button"
                data-testid="otp-no-account-signup"
                onClick={() => resetMessagesAndStep("password", "signup")}
                className="font-semibold text-primary hover:underline cursor-pointer"
              >
                Create Account
              </button>
            </div>
          )}
          {accountExists && (
            <div
              className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs"
              data-testid="account-exists-actions"
            >
              <button
                type="button"
                onClick={() => resetMessagesAndStep("password", "signin")}
                className="font-semibold text-primary hover:underline cursor-pointer"
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => resetMessagesAndStep("otp")}
                className="font-semibold text-primary hover:underline cursor-pointer"
              >
                Use Email OTP
              </button>
              <button
                type="button"
                onClick={() => resetMessagesAndStep("password", "set_password")}
                className="font-semibold text-primary hover:underline cursor-pointer"
              >
                Set or Forgot Password
              </button>
            </div>
          )}
        </div>
      )}
      {success && (
        <div className="p-3 text-sm text-emerald-700 bg-emerald-50 rounded-md border border-emerald-200">
          {success}
        </div>
      )}

      {/* ==================== TAB 1 & 2: EMAIL & PASSWORD ==================== */}
      {authMethod === "password" && step === 1 && (
        <>
          {passwordMode === "signin" && (
            <div className="space-y-4">
              <form onSubmit={handlePasswordSignIn} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email-pw" className="text-slate-700">
                    Email address
                  </Label>
                  <Input
                    id="email-pw"
                    type="email"
                    placeholder="name@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className="bg-slate-50"
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="password-signin" className="text-slate-700">
                      Password
                    </Label>
                    <button
                      type="button"
                      onClick={() =>
                        resetMessagesAndStep("password", "set_password")
                      }
                      className="text-xs font-medium text-primary hover:underline cursor-pointer"
                    >
                      Set or Forgot Password?
                    </button>
                  </div>
                  <div className="relative">
                    <Input
                      id="password-signin"
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter your password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      autoComplete="current-password"
                      className="bg-slate-50 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((prev) => !prev)}
                      aria-label={
                        showPassword ? "Hide password" : "Show password"
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <Button
                  type="submit"
                  className="w-full text-md h-10"
                  disabled={!!loading}
                >
                  {loading === "password-signin" ? "Signing in" : "Sign In"}
                </Button>
              </form>

              <div className="text-center text-xs text-slate-500 pt-1">
                New to {tenant?.name || "Naviera"}?{" "}
                <button
                  type="button"
                  data-testid="switch-to-signup-link"
                  onClick={() => resetMessagesAndStep("password", "signup")}
                  className="font-semibold text-primary hover:underline cursor-pointer"
                >
                  Create an account
                </button>
              </div>
            </div>
          )}

          {passwordMode === "signup" && (
            <div className="space-y-4">
              <form onSubmit={handlePasswordSignUp} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="fullname-signup" className="text-slate-700">
                    Full name
                  </Label>
                  <Input
                    id="fullname-signup"
                    type="text"
                    placeholder="Your full name"
                    autoComplete="name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="bg-slate-50"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="email-signup" className="text-slate-700">
                    Email address
                  </Label>
                  <Input
                    id="email-signup"
                    type="email"
                    placeholder="name@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className="bg-slate-50"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password-signup" className="text-slate-700">
                    Create password (min. {MIN_PASSWORD_LENGTH} characters)
                  </Label>
                  <div className="relative">
                    <Input
                      id="password-signup"
                      type={showPassword ? "text" : "password"}
                      placeholder="Create a strong password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      minLength={MIN_PASSWORD_LENGTH}
                      autoComplete="new-password"
                      className="bg-slate-50 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((prev) => !prev)}
                      aria-label={
                        showPassword ? "Hide password" : "Show password"
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <input
                    id="terms-signup"
                    type="checkbox"
                    data-testid="signup-terms-checkbox"
                    checked={termsAccepted}
                    onChange={(e) => setTermsAccepted(e.target.checked)}
                    required
                    className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-slate-300 accent-primary"
                  />
                  <Label
                    htmlFor="terms-signup"
                    className="text-xs font-normal leading-snug text-slate-600 cursor-pointer"
                  >
                    <span>
                      I agree to the{" "}
                      <a
                        href={routeTo(LEGAL_PATHS.terms)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-primary hover:underline"
                      >
                        Terms
                      </a>{" "}
                      and{" "}
                      <a
                        href={routeTo(LEGAL_PATHS.privacy)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-primary hover:underline"
                      >
                        Privacy Policy
                      </a>{" "}
                      and will not ship{" "}
                      <a
                        href={routeTo(LEGAL_PATHS.prohibited)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-primary hover:underline"
                      >
                        prohibited items
                      </a>
                      .
                    </span>
                  </Label>
                </div>

                <Button
                  type="submit"
                  data-testid="submit-create-account"
                  className="w-full text-md h-10"
                  disabled={!!loading}
                >
                  {loading === "password-signup"
                    ? "Creating account"
                    : "Create Account"}
                </Button>
              </form>

              <div className="text-center text-xs text-slate-500 pt-1">
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => resetMessagesAndStep("password", "signin")}
                  className="font-semibold text-primary hover:underline cursor-pointer"
                >
                  Sign in with password
                </button>
              </div>
            </div>
          )}

          {passwordMode === "set_password" && (
            <div className="space-y-4">
              <form onSubmit={handleRequestPasswordOtp} className="space-y-4">
                <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 border border-slate-200">
                  Enter your email and choose a new password. We will send a
                  6-digit verification code to confirm and save your password.
                </div>

                <div className="space-y-2">
                  <Label htmlFor="email-reset" className="text-slate-700">
                    Email address
                  </Label>
                  <Input
                    id="email-reset"
                    type="email"
                    placeholder="name@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className="bg-slate-50"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password-reset" className="text-slate-700">
                    New password (min. {MIN_PASSWORD_LENGTH} characters)
                  </Label>
                  <div className="relative">
                    <Input
                      id="password-reset"
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter new password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      minLength={MIN_PASSWORD_LENGTH}
                      autoComplete="new-password"
                      className="bg-slate-50 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((prev) => !prev)}
                      aria-label={
                        showPassword ? "Hide password" : "Show password"
                      }
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <Button
                  type="submit"
                  className="w-full text-md h-10"
                  disabled={!!loading}
                >
                  {loading === "set-password-otp"
                    ? "Sending verification code"
                    : "Send Code to Set Password"}
                </Button>
              </form>

              <div className="text-center text-xs text-slate-500 pt-1">
                <button
                  type="button"
                  onClick={() => resetMessagesAndStep("password", "signin")}
                  className="font-semibold text-primary hover:underline cursor-pointer"
                >
                  Back to password sign in
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ==================== TAB 3: EMAIL OTP ==================== */}
      {authMethod === "otp" && step === 1 && (
        <form onSubmit={handleSendOtp} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email-otp" className="text-slate-700">
              Email address
            </Label>
            <Input
              id="email-otp"
              type="email"
              placeholder="name@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="bg-slate-50"
            />
          </div>
          <Button
            type="submit"
            className="w-full text-md h-10"
            disabled={!!loading}
          >
            {loading === "email" ? "Sending code" : "Send 6-Digit OTP"}
          </Button>
        </form>
      )}

      {/* ==================== GOOGLE OAUTH (STEP 1) ==================== */}
      {step === 1 && isOAuthEnabled && (
        <>
          <div className="relative my-4">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">
                Or continue with
              </span>
            </div>
          </div>

          <Button
            type="button"
            variant="outline"
            className="w-full text-md h-12 bg-white"
            onClick={() => handleOAuthLogin("google")}
            disabled={!!loading}
          >
            <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
              <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                fill="#4285F4"
              />
              <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
              />
              <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                fill="#EA4335"
              />
            </svg>
            {loading === "google" ? "Connecting" : "Sign in with Google"}
          </Button>
        </>
      )}

      {/* ==================== STEP 2: 6-DIGIT OTP VERIFICATION ==================== */}
      {step === 2 && (
        <form onSubmit={handleVerifyOtp} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="otp" className="text-slate-700">
              Verification Code (sent to {email})
            </Label>
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
          <Button
            type="submit"
            className="w-full text-md h-10"
            disabled={!!loading}
          >
            {loading === "verify"
              ? "Verifying"
              : authMethod === "password" && passwordMode === "set_password"
                ? "Verify & Save Password"
                : "Verify & Sign In"}
          </Button>

          <div className="text-center mt-4">
            <button
              type="button"
              onClick={() => {
                setStep(1);
                setSuccess(null);
                setError(null);
                setOtp("");
              }}
              className="text-sm text-slate-500 hover:text-primary transition-colors cursor-pointer"
            >
              Use a different email or method
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
