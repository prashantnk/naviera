// src/components/blocks/app-sidebar.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { cn } from "@/lib/utils";
import { Home, MapPin, Package, PlusCircle, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function AppSidebar() {
    const { tenant, routeTo } = useTenant();
    const pathname = usePathname();

    // Navigation schema
    const navItems = [
        { name: "Dashboard", href: "/dashboard", icon: Home },
        { name: "Shipments", href: "/shipments", icon: Package },
        { name: "Create Booking", href: "/shipments/new", icon: PlusCircle },
        { name: "Address Book", href: "/address-book", icon: MapPin },
        { name: "Settings", href: "/settings", icon: Settings },
    ];

    return (
        <aside className="w-64 bg-slate-900 flex-shrink-0 hidden md:flex flex-col min-h-screen text-slate-300">
            {/* Sidebar Header: Branding */}
            <div className="h-16 flex items-center px-6 border-b border-slate-800 bg-slate-950">
                <span className="text-lg font-bold text-white tracking-tight">
                    {tenant?.name || "Naviera"}
                </span>
            </div>

            {/* Sidebar Navigation */}
            <nav className="flex-1 py-6 px-3 space-y-1">
                {navItems.map((item) => {
                    // Resolve the environment-safe URL
                    const resolvedHref = routeTo(item.href);
                    // Check if this route is currently active
                    const isActive = pathname === resolvedHref || pathname?.startsWith(`${resolvedHref}/`);

                    return (
                        <Link
                            key={item.name}
                            href={resolvedHref}
                            className={cn(
                                "flex items-center gap-3 px-3 py-2 rounded-md transition-colors text-sm font-medium",
                                isActive
                                    ? "bg-primary text-primary-foreground" // Use the tenant's primary color when active!
                                    : "hover:bg-slate-800 hover:text-white"
                            )}
                        >
                            <item.icon className="h-4 w-4" />
                            {item.name}
                        </Link>
                    );
                })}
            </nav>
        </aside>
    );
}