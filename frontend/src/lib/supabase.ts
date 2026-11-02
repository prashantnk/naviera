// frontend/src/lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// We cache the clients in memory so we don't recreate them on every React render
const clients = new Map();

export const getSupabaseClient = (tenantSlug: string) => {
  // If we haven't created a client for this tenant yet, make one
  if (!clients.has(tenantSlug)) {
    const isBrowser = typeof window !== "undefined";

    // 🔥 FIX: Make the proxy URL absolute by prepending window.location.origin
    const proxyUrl = isBrowser
      ? `${window.location.origin}/supabase-proxy`
      : supabaseUrl;

    clients.set(
      tenantSlug,
      createClient(proxyUrl, supabaseAnonKey, {
        auth: {
          // Isolate the local storage key by tenant!
          storageKey: `sb-${tenantSlug}-auth-token`,
        },
      })
    );
  }

  return clients.get(tenantSlug);
};

export const resetSupabaseClient = (tenantSlug: string) => {
  clients.delete(tenantSlug);
};

/** Max time we wait for Supabase's own sign-out call before clearing locally anyway. */
const SIGN_OUT_NETWORK_TIMEOUT_MS = 1500;

/**
 * Storage key supabase-js uses when no custom `storageKey` is set
 * (`sb-<project-ref>-auth-token`), derived from the project URL.
 */
function _defaultProjectStorageKey(): string | null {
  try {
    const projectRef = new URL(supabaseUrl).hostname.split(".")[0];
    return projectRef ? `sb-${projectRef}-auth-token` : null;
  } catch {
    return null;
  }
}

/**
 * Removes every locally stored session for this tenant.
 *
 * @param tenantSlug - Tenant whose session keys are cleared.
 */
export function clearStoredSession(tenantSlug: string): void {
  if (typeof window === "undefined") return;
  const keys = [`sb-${tenantSlug}-auth-token`, _defaultProjectStorageKey()];
  keys.forEach((key) => {
    if (key) window.localStorage.removeItem(key);
  });
  resetSupabaseClient(tenantSlug);
}

/**
 * Reliable logout.
 *
 * supabase-js calls GoTrue `/logout` first and, when that call fails (for
 * example for backend-minted password sessions GoTrue does not know), it
 * returns early WITHOUT clearing the stored session, so the login page would
 * find the old session and bounce the user back into the app. We therefore
 * give the network call a short timeout, always clear local storage
 * ourselves, and finish with a hard navigation that drops all in-memory state
 * (React Query caches, Supabase refresh timers).
 *
 * @param tenantSlug - Tenant being signed out of.
 * @param redirectTo - Absolute or tenant-resolved path to land on (e.g. `routeTo("/login")`).
 */
export async function signOutAndRedirect(
  tenantSlug: string,
  redirectTo: string
): Promise<void> {
  const supabase = getSupabaseClient(tenantSlug);
  const timeout = new Promise<void>((resolve) =>
    setTimeout(resolve, SIGN_OUT_NETWORK_TIMEOUT_MS)
  );
  await Promise.race([
    supabase.auth.signOut({ scope: "local" }).catch(() => undefined),
    timeout,
  ]);
  clearStoredSession(tenantSlug);
  window.location.replace(redirectTo);
}
