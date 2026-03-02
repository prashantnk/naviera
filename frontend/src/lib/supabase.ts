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
