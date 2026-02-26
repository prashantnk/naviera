// src/components/blocks/app-header.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { getSupabaseClient } from "@/lib/supabase";
import { Bell, LogOut, Search, User } from "lucide-react";
import { useRouter } from "next/navigation";

export function AppHeader() {
    const { routeTo, tenantSlug } = useTenant();
    const router = useRouter();
    const supabase = getSupabaseClient(tenantSlug);

    // The Logout Function
    const handleLogout = async () => {
        // 1. Destroy the session in Supabase (clears localStorage)
        await supabase.auth.signOut();

        // 2. Safely route back to this specific tenant's login page
        router.push(routeTo("/login"));
    };

    return (
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 sticky top-0 z-40">

            {/* Global Search */}
            <div className="flex items-center flex-1 max-w-md">
                <div className="relative w-full">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
                    <Input
                        type="text"
                        placeholder="Search Tracking ID, Name, Phone..."
                        className="w-full pl-9 bg-slate-50 border-transparent focus-visible:bg-white"
                    />
                </div>
            </div>

            {/* Right Actions */}
            <div className="flex items-center gap-4">
                <Button variant="ghost" size="icon" className="text-slate-500">
                    <Bell className="h-5 w-5" />
                </Button>

                {/* User Profile Dropdown */}
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary cursor-pointer hover:bg-primary/30 transition-colors">
                            <User className="h-4 w-4" />
                        </div>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent align="end" className="w-56">
                        <DropdownMenuLabel>My Account</DropdownMenuLabel>
                        <DropdownMenuSeparator />

                        {/* Logout Button */}
                        <DropdownMenuItem
                            className="text-red-600 cursor-pointer focus:text-red-600 focus:bg-red-50"
                            onClick={handleLogout}
                        >
                            <LogOut className="mr-2 h-4 w-4" />
                            <span>Log out</span>
                        </DropdownMenuItem>

                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </header>
    );
}