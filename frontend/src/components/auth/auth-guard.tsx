// frontend/src/components/auth/auth-guard.tsx
"use client";

import { ApiError, ServiceScope, UserRead, UsersService } from "@/api_client";
import { resolveCapabilities, type UserCapabilities } from "@/components/auth/capabilities";
import { useTenant } from "@/components/providers/tenant-provider";
import { TENANT_ACCESS_CHECK_EVENT } from "@/lib/api-config";
import {
  clearStoredSession,
  getSupabaseClient,
  signOutAndRedirect,
} from "@/lib/supabase";
import { CloudOff, Loader2, ShieldOff } from "lucide-react";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";

/** HTTP statuses from `GET /users/me` that mean "signed in, but not allowed here". */
const INACTIVE_USER_STATUS = 400;
const NO_TENANT_ACCESS_STATUS = 403;
/** `GET /users/me` status for a missing / expired / invalid token: sign in again. */
const SIGNED_OUT_STATUS = 401;

/** Delay before the guard retries `/users/me` on its own after a server / network error. */
export const PROFILE_RETRY_DELAY_MS = 5_000;

/** Shown while the backend is unreachable on first load (deploy, restart, network blip). */
export const SERVER_UNREACHABLE_MESSAGE =
  "We couldn't reach the server. You are still signed in; we'll retry in a few seconds.";

/** Thrown when there is no stored Supabase session at all. */
class NoSessionError extends Error {
  constructor() {
    super("No valid session");
    this.name = "NoSessionError";
  }
}

/**
 * Whether a first-load failure means the login itself is gone (so we sign out), as
 * opposed to a temporary server / network problem (so we keep the session and retry).
 *
 * @param error - Error from the session lookup or `GET /users/me`.
 * @returns True for "no session" and HTTP 401 only.
 */
export function isSignedOutError(error: unknown): boolean {
  if (error instanceof NoSessionError) return true;
  return error instanceof ApiError && error.status === SIGNED_OUT_STATUS;
}

/**
 * Minimum gap between mid-session access re-checks (API 403s, tab focus), so a
 * burst of refused calls or quick tab switches costs one `/users/me` call.
 */
export const ACCESS_RECHECK_MIN_INTERVAL_MS = 5_000;

/**
 * Maps a `/users/me` failure to a user-facing explanation, or null when the
 * failure should fall back to the normal "sign in again" redirect.
 *
 * @param error - Error thrown by the generated API client.
 * @returns Explanation for deactivated / no-access accounts, otherwise null.
 */
function resolveAccessDeniedMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === INACTIVE_USER_STATUS) {
    return "Your account has been deactivated. Please contact your account manager to restore access.";
  }
  if (error.status === NO_TENANT_ACCESS_STATUS) {
    return "This login doesn't have access to this workspace yet. Ask an administrator to add you, or sign in with a different email.";
  }
  return null;
}

interface UserContextType {
  user: UserRead | null;
  /** Any staff member (owner, admin, operations, support, read-only). */
  isAdmin: boolean;
  canManageTeam: boolean;
  /** Role capability map mirroring `backend/app/core/permissions.py`. */
  capabilities: UserCapabilities;
  serviceScope: ServiceScope;
  canAccessB2C: boolean;
  canAccessB2B: boolean;
  refreshUser: () => Promise<void>;
}
const UserContext = createContext<UserContextType | undefined>(undefined);

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [isChecking, setIsChecking] = useState(true);
  const [accessDenied, setAccessDenied] = useState<string | null>(null);
  const [serverUnreachable, setServerUnreachable] = useState(false);
  const [profileAttempt, setProfileAttempt] = useState(0);

  const { routeTo, tenantSlug } = useTenant();
  const supabase = getSupabaseClient(tenantSlug);

  // Mid-session access re-check state (see the re-check effect below).
  const recheckInFlightRef = useRef(false);
  const lastAccessCheckAtRef = useRef(0);

  const refreshUser = React.useCallback(async () => {
    try {
      const profile = await UsersService.getMyProfile();
      setUser(profile);
    } catch {
      // Ignore transient refresh errors
    }
  }, []);

  useEffect(() => {
    const handleProfileUpdated = () => {
      void refreshUser();
    };
    window.addEventListener("user-profile-updated", handleProfileUpdated);
    return () => {
      window.removeEventListener("user-profile-updated", handleProfileUpdated);
    };
  }, [refreshUser]);

  /**
   * Re-validates the tenant membership while the app is open (API 403s, tab focus).
   *
   * The mount check below runs once; if the user row is removed or deactivated
   * later, every API call starts failing with 403 while the shell keeps rendering.
   * Checks are de-duplicated and throttled: a trigger inside the throttle window
   * schedules one trailing check instead of being dropped. Only a 400/403 from
   * `/users/me` swaps the page for the "Access not available" screen; other
   * errors are transient.
   */
  useEffect(() => {
    if (isChecking || accessDenied) return;
    let trailingTimer: ReturnType<typeof setTimeout> | null = null;

    const recheckAccess = (): void => {
      if (recheckInFlightRef.current) return;
      const waitMs = lastAccessCheckAtRef.current + ACCESS_RECHECK_MIN_INTERVAL_MS - Date.now();
      if (waitMs > 0) {
        trailingTimer ??= setTimeout(() => {
          trailingTimer = null;
          recheckAccess();
        }, waitMs);
        return;
      }
      recheckInFlightRef.current = true;
      void (async () => {
        try {
          setUser(await UsersService.getMyProfile());
        } catch (error) {
          const accessMessage = resolveAccessDeniedMessage(error);
          if (accessMessage) setAccessDenied(accessMessage);
        } finally {
          lastAccessCheckAtRef.current = Date.now();
          recheckInFlightRef.current = false;
        }
      })();
    };
    const handleFocus = () => {
      if (document.visibilityState === "visible") recheckAccess();
    };

    window.addEventListener(TENANT_ACCESS_CHECK_EVENT, recheckAccess);
    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleFocus);
    return () => {
      window.removeEventListener(TENANT_ACCESS_CHECK_EVENT, recheckAccess);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleFocus);
      if (trailingTimer) clearTimeout(trailingTimer);
    };
  }, [isChecking, accessDenied]);

  useEffect(() => {
    const checkAuthAndFetchProfile = async () => {
      try {
        const {
          data: { session },
          error: sessionError,
        } = await supabase.auth.getSession();

        // If no session or an error occurs, throw immediately to hit the catch block
        if (sessionError || !session) {
          throw new NoSessionError();
        }

        const profile = await UsersService.getMyProfile();
        setUser(profile);
        lastAccessCheckAtRef.current = Date.now();
        setServerUnreachable(false);
        setIsChecking(false);
      } catch (error) {
        console.error("Auth check failed or token corrupted:", error);

        // A valid login that the backend refuses (deactivated user / no access to
        // this tenant) must not silently bounce to the login page in a loop:
        // explain it instead and offer an explicit sign-out.
        const accessMessage = resolveAccessDeniedMessage(error);
        if (accessMessage) {
          setAccessDenied(accessMessage);
          setIsChecking(false);
          return;
        }

        // A server error or a network blip (backend restart, deploy) is not a reason to
        // sign the user out: keep the session, say so, and retry on our own.
        if (!isSignedOutError(error)) {
          setServerUnreachable(true);
          setIsChecking(false);
          return;
        }

        // 1-2. Wipe every stored session for this tenant without waiting on the network.
        clearStoredSession(tenantSlug);

        // 3. 🔥 THE HARD REDIRECT:
        // We intentionally avoid Next.js router.push() here.
        // Using window.location.href forces the browser to destroy the Javascript
        // context, permanently killing Supabase's rogue background refresh timers!
        const currentPath = window.location.pathname + window.location.search;
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.href = `${routeTo("/login")}?next=${encodeURIComponent(
          currentPath
        )}`;
      }
    };

    checkAuthAndFetchProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug, routeTo, profileAttempt]);

  const retryProfile = React.useCallback(() => {
    setIsChecking(true);
    setProfileAttempt((attempt) => attempt + 1);
  }, []);

  // While the server is unreachable, retry automatically every few seconds.
  useEffect(() => {
    if (!serverUnreachable) return;
    const timer = setTimeout(retryProfile, PROFILE_RETRY_DELAY_MS);
    return () => clearTimeout(timer);
  }, [serverUnreachable, retryProfile]);

  if (isChecking) {
    return (
      <div className="flex min-h-screen w-full flex-1 items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-slate-500 font-medium">Securing session</p>
        </div>
      </div>
    );
  }

  if (serverUnreachable) {
    return (
      <div className="flex min-h-screen w-full flex-1 items-center justify-center bg-slate-50 p-6">
        <div
          data-testid="auth.server-unreachable"
          className="max-w-md space-y-4 rounded-2xl border border-border bg-card p-8 text-center shadow-sm"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <CloudOff className="h-6 w-6 text-primary" />
          </div>
          <h2 className="text-xl font-bold text-foreground">Can&apos;t reach the server</h2>
          <p className="text-sm text-muted-foreground">{SERVER_UNREACHABLE_MESSAGE}</p>
          <button
            type="button"
            data-testid="auth.server-unreachable.retry"
            onClick={retryProfile}
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Retry now
          </button>
        </div>
      </div>
    );
  }

  if (accessDenied) {
    const handleSignOut = async () => {
      await signOutAndRedirect(tenantSlug, routeTo("/login"));
    };
    return (
      <div className="flex min-h-screen w-full flex-1 items-center justify-center bg-slate-50 p-6">
        <div
          data-testid="auth.access-denied"
          className="max-w-md space-y-4 rounded-2xl border border-border bg-card p-8 text-center shadow-sm"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <ShieldOff className="h-6 w-6 text-primary" />
          </div>
          <h2 className="text-xl font-bold text-foreground">Access not available</h2>
          <p className="text-sm text-muted-foreground">{accessDenied}</p>
          <button
            type="button"
            data-testid="auth.access-denied.sign-out"
            onClick={handleSignOut}
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  const capabilities = resolveCapabilities(user?.role);
  // `isAdmin` keeps its historical meaning: any staff member (staff-wide read visibility).
  const isAdmin = capabilities.isStaff;
  const serviceScope = user?.service_scope || ServiceScope.B2C;
  const canAccessB2C =
    isAdmin ||
    serviceScope === ServiceScope.B2C ||
    serviceScope === ServiceScope.BOTH;
  const canAccessB2B =
    isAdmin ||
    serviceScope === ServiceScope.B2B ||
    serviceScope === ServiceScope.BOTH;
  const canManageTeam = capabilities.canManageTeam;

  return (
    <UserContext.Provider
      value={{
        user,
        isAdmin,
        canManageTeam,
        capabilities,
        serviceScope,
        canAccessB2C,
        canAccessB2B,
        refreshUser,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error("useUser must be used within an AuthGuard");
  }
  return context;
}
