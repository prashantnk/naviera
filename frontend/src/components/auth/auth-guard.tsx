// frontend/src/components/auth/auth-guard.tsx
"use client";

import { UserRead, UserRole, UsersService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { getSupabaseClient } from "@/lib/supabase";
import { Loader2 } from "lucide-react";
import React, { createContext, useContext, useEffect, useState } from "react";

interface UserContextType {
  user: UserRead | null;
  isAdmin: boolean;
}
const UserContext = createContext<UserContextType | undefined>(undefined);

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  const { routeTo, tenantSlug } = useTenant();
  const supabase = getSupabaseClient(tenantSlug);

  useEffect(() => {
    const checkAuthAndFetchProfile = async () => {
      try {
        const {
          data: { session },
          error: sessionError,
        } = await supabase.auth.getSession();

        // If no session or an error occurs, throw immediately to hit the catch block
        if (sessionError || !session) {
          throw new Error("No valid session");
        }

        const profile = await UsersService.getMyProfile();
        setUser(profile);
        setIsChecking(false);
      } catch (error) {
        console.error("Auth check failed or token corrupted:", error);

        // 1. Programmatically wipe the local storage
        localStorage.removeItem(`sb-${tenantSlug}-auth-token`);

        // 2. Try a graceful sign out (but don't block if the network is dead)
        await supabase.auth.signOut().catch(() => {});

        // 3. 🔥 THE HARD REDIRECT:
        // We intentionally avoid Next.js router.push() here.
        // Using window.location.href forces the browser to destroy the Javascript
        // context, permanently killing Supabase's rogue background refresh timers!
        const currentPath = window.location.pathname + window.location.search;
        window.location.href = `${routeTo("/login")}?next=${encodeURIComponent(
          currentPath
        )}`;
      }
    };

    checkAuthAndFetchProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug, routeTo]);

  if (isChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-slate-500 font-medium">Securing session...</p>
        </div>
      </div>
    );
  }

  const isAdmin =
    user?.role === UserRole.ADMIN || user?.role === UserRole.OWNER;

  return (
    <UserContext.Provider value={{ user, isAdmin }}>
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
