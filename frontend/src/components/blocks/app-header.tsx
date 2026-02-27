// frontend/src/components/blocks/app-header.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
    DropdownMenu, DropdownMenuContent, DropdownMenuItem,
    DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { getSupabaseClient } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { Bell, Globe, Home, LogOut, MapPin, Menu, Package, PlusCircle, Search, Settings, User, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

export function AppHeader() {
    const { routeTo, tenantSlug, tenant } = useTenant();
    const router = useRouter();
    const pathname = usePathname();
    const supabase = getSupabaseClient(tenantSlug);

    // Mobile State
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

    const handleLogout = async () => {
        await supabase.auth.signOut();
        router.push(routeTo("/login"));
    };

    // Replicate Sidebar Links for Mobile
    const navItems = [
        { name: "Dashboard", href: "/dashboard", icon: Home },
        { name: "Shipments", href: "/shipments", icon: Package },
        { name: "Create Booking", href: "/shipments/new", icon: PlusCircle },
        { name: "Address Book", href: "/address-book", icon: MapPin },
        { name: "Settings", href: "/settings", icon: Settings },
    ];

    const checkIsActive = (href: string) => {
        const resolvedHref = routeTo(href);
        if (!pathname) return false;
        if (pathname === resolvedHref) return true;
        if (href === "/shipments" && pathname.startsWith(`${resolvedHref}/`) && !pathname.includes("/new")) return true;
        return false;
    };

    return (
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-4 md:px-6 sticky top-0 z-40">

            {/* 🔥 MOBILE MENU TOGGLE (Left Side) */}
            <div className="flex md:hidden items-center mr-2">
                <Button variant="ghost" size="icon" onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}>
                    {isMobileMenuOpen ? <X className="h-6 w-6 text-slate-900" /> : <Menu className="h-6 w-6 text-slate-900" />}
                </Button>
            </div>

            {/* Global Search */}
            <div className="flex items-center flex-1 max-w-md">
                <div className="relative w-full">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
                    <Input
                        type="text"
                        placeholder="Search Tracking ID..."
                        className="w-full pl-9 bg-slate-50 border-transparent focus-visible:bg-white"
                    />
                </div>
            </div>

            {/* Right Actions */}
            <div className="flex items-center gap-2 md:gap-4 ml-2">
                <Button variant="ghost" size="icon" className="text-slate-500 hidden sm:flex">
                    <Bell className="h-5 w-5" />
                </Button>

                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary cursor-pointer hover:bg-primary/30 transition-colors">
                            <User className="h-4 w-4" />
                        </div>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                        <DropdownMenuLabel>My Account</DropdownMenuLabel>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="text-red-600 cursor-pointer" onClick={handleLogout}>
                            <LogOut className="mr-2 h-4 w-4" />
                            <span>Log out</span>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>

            {/* 🔥 MOBILE DROP DOWN NAV */}
            {isMobileMenuOpen && (
                <div className="md:hidden absolute top-full left-0 w-full bg-slate-900 text-slate-300 border-b border-slate-800 shadow-2xl flex flex-col p-4 animate-in slide-in-from-top-2">
                    <div className="mb-4 px-3 pb-4 border-b border-slate-800">
                        <span className="text-lg font-bold text-white tracking-tight">{tenant?.name || "Naviera"}</span>
                    </div>
                    <nav className="flex flex-col gap-1">
                        {navItems.map((item) => {
                            const isActive = checkIsActive(item.href);
                            return (
                                <Link
                                    key={item.name} href={routeTo(item.href)} onClick={() => setIsMobileMenuOpen(false)}
                                    className={cn("flex items-center gap-3 px-3 py-3 rounded-md transition-colors text-base font-medium", isActive ? "bg-primary text-primary-foreground shadow-sm" : "hover:bg-slate-800 hover:text-white")}
                                >
                                    <item.icon className="h-5 w-5" />
                                    {item.name}
                                </Link>
                            );
                        })}
                    </nav>
                    <div className="mt-4 pt-4 border-t border-slate-800">
                        <Link href={routeTo("/")} onClick={() => setIsMobileMenuOpen(false)} className="flex items-center justify-center gap-2 w-full py-3 rounded-md bg-slate-800 text-white transition-colors text-sm font-medium">
                            <Globe className="h-4 w-4" /> Public Website
                        </Link>
                    </div>
                </div>
            )}
        </header>
    );
}