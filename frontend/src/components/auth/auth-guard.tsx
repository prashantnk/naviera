// src/components/auth/auth-guard.tsx
"use client";

import { UserRead, UserRole, UsersService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { getSupabaseClient } from "@/lib/supabase";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { createContext, useContext, useEffect, useState } from "react";

// 1. Upgraded Context Type
interface UserContextType {
    user: UserRead | null;
    isAdmin: boolean;
}
const UserContext = createContext<UserContextType | undefined>(undefined);

export function AuthGuard({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<UserRead | null>(null);
    const [isChecking, setIsChecking] = useState(true);

    const router = useRouter();
    const { routeTo, tenantSlug } = useTenant();
    const supabase = getSupabaseClient(tenantSlug);

    useEffect(() => {
        const checkAuthAndFetchProfile = async () => {
            try {
                const { data: { session } } = await supabase.auth.getSession();

                if (!session) {
                    // 🔥 NEW: Capture current URL using window.location for safe client-side reading
                    const currentPath = window.location.pathname + window.location.search;
                    router.push(`${routeTo("/login")}?next=${encodeURIComponent(currentPath)}`);
                    return;
                }

                const profile = await UsersService.getMyProfile();
                setUser(profile);
            } catch (error) {
                console.error("Auth check failed:", error);
                const currentPath = window.location.pathname + window.location.search;
                router.push(`${routeTo("/login")}?next=${encodeURIComponent(currentPath)}`);
            } finally {
                setIsChecking(false);
            }
        };

        checkAuthAndFetchProfile();
    }, [router, routeTo, supabase]);

    if (isChecking) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-slate-50">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
            </div>
        );
    }

    // 2. Calculate isAdmin ONCE here
    const isAdmin = user?.role === UserRole.ADMIN || user?.role === UserRole.OWNER;

    return (
        <UserContext.Provider value={{ user, isAdmin }}>
            {children}
        </UserContext.Provider>
    );
}

// Custom hook
export function useUser() {
    const context = useContext(UserContext);
    if (context === undefined) {
        throw new Error("useUser must be used within an AuthGuard");
    }
    return context;
}