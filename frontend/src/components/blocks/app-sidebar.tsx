// src/components/blocks/app-sidebar.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { cn } from "@/lib/utils";
import { Globe, Home, MapPin, Package, PlusCircle, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";


export function AppSidebar() {
    const { tenant, routeTo } = useTenant();
    const pathname = usePathname();

    const navItems = [
        { name: "Dashboard", href: "/dashboard", icon: Home },
        { name: "Shipments", href: "/shipments", icon: Package },
        { name: "Create Booking", href: "/shipments/new", icon: PlusCircle },
        { name: "Address Book", href: "/address-book", icon: MapPin },
        { name: "Settings", href: "/settings", icon: Settings },
    ];

    // Intelligent Route Matching
    const checkIsActive = (href: string) => {
        const resolvedHref = routeTo(href);
        if (!pathname) return false;

        // Exact match (e.g. /dashboard or /shipments/new)
        if (pathname === resolvedHref) return true;

        // If we are looking at the generic /shipments link, we ONLY want to highlight it 
        // if we are looking at a specific shipment detail page like /shipments/1234.
        // We DO NOT want to highlight it if we are on /shipments/new!
        if (href === "/shipments" && pathname.startsWith(`${resolvedHref}/`) && !pathname.includes("/new")) {
            return true;
        }

        return false;
    };

    return (
        <aside className="w-64 bg-slate-900 flex-shrink-0 hidden md:flex flex-col min-h-screen text-slate-300">
            <div className="h-16 flex items-center px-6 border-b border-slate-800 bg-slate-950">
                <span className="text-lg font-bold text-white tracking-tight truncate">
                    {tenant?.name || "Naviera"}
                </span>
            </div>

            <nav className="flex-1 py-6 px-3 space-y-1">
                {navItems.map((item) => {
                    const resolvedHref = routeTo(item.href);
                    const isActive = checkIsActive(item.href);

                    return (
                        <Link
                            key={item.name}
                            href={resolvedHref}
                            className={cn(
                                "flex items-center gap-3 px-3 py-2 rounded-md transition-colors text-sm font-medium",
                                isActive
                                    ? "bg-primary text-primary-foreground shadow-sm"
                                    : "hover:bg-slate-800 hover:text-white"
                            )}
                        >
                            <item.icon className="h-4 w-4" />
                            {item.name}
                        </Link>
                    );
                })}
            </nav>
            {/* 🔥 NEW: Return to Public Site Footer */}
            <div className="p-4 border-t border-slate-800">
                <Link
                    href={routeTo("/")}
                    className="flex items-center justify-center gap-2 w-full py-2.5 px-3 rounded-md bg-slate-800/50 hover:bg-slate-800 text-slate-400 hover:text-white transition-colors text-sm font-medium"
                >
                    <Globe className="h-4 w-4" />
                    Public Website
                </Link>
            </div>
        </aside>
    );
}