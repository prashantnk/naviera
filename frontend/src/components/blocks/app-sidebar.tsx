// frontend/src/components/blocks/app-sidebar.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  ChevronLeft,
  ChevronRight,
  Home,
  MapPin,
  Package,
  Package2,
  PlusCircle,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useUser } from "@/components/auth/auth-guard";
import { Users } from "lucide-react"; // add Users to lucide-react import

export function AppSidebar() {
  const { tenant, routeTo } = useTenant();
  const pathname = usePathname();
  const brand = tenant?.settings?.brand;

  const [isCollapsed, setIsCollapsed] = useState(true);
  const [isHovered, setIsHovered] = useState(false);

  // Sidebar is expanded if it's NOT collapsed, OR if the user is hovering over it.
  const isExpanded = !isCollapsed || isHovered;
  const { isAdmin } = useUser();

  const baseNavItems = [
    { name: "Dashboard", href: "/dashboard", icon: Home },
    { name: "Shipments", href: "/shipments", icon: Package },
    { name: "Create Booking", href: "/shipments/new", icon: PlusCircle },
    { name: "Address Book", href: "/address-book", icon: MapPin },
  ];

  const adminNavItems = [
    { name: "Team & Access", href: "/team", icon: Users },
    { name: "Settings", href: "/settings", icon: Settings },
  ];

  const navItems = isAdmin ? [...baseNavItems, ...adminNavItems] : baseNavItems;

  const checkIsActive = (href: string) => {
    const resolvedHref = routeTo(href);
    if (!pathname) return false;
    if (pathname === resolvedHref) return true;
    if (
      href === "/shipments" &&
      pathname.startsWith(`${resolvedHref}/`) &&
      !pathname.includes("/new")
    )
      return true;
    return false;
  };

  return (
    <>
      {/* 🔥 THE SPACER: This holds the physical space in the DOM so the main content doesn't jump! */}
      <div
        className={cn(
          "hidden md:block shrink-0 transition-[width] duration-300 ease-in-out z-0",
          isCollapsed ? "w-[72px]" : "w-64"
        )}
      />

      {/* 🔥 THE ACTUAL SIDEBAR: Fixed position. It will float over the content when hovered. */}
      <aside
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={cn(
          "bg-slate-950 fixed left-0 top-0 bottom-0 hidden md:flex flex-col border-r border-slate-800 z-50 transition-all duration-300 ease-in-out overflow-hidden",
          isExpanded ? "w-64" : "w-[72px]",
          isCollapsed && isHovered ? "shadow-2xl" : ""
        )}
      >
        {/* 🔥 THE LOGO HEADER: bg-white cleanly integrates with the AppHeader next to it! */}
        <div className="h-16 flex items-center justify-center px-3 border-b border-slate-200 bg-white shrink-0">
          <Link
            href={routeTo("/dashboard")}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity w-full overflow-hidden justify-center"
          >
            {brand?.logo_url ? (
              <img
                src={brand.logo_url}
                alt={tenant?.name}
                className={cn(
                  "object-contain transition-all duration-300",
                  // Smoothly shrink the actual logo image when collapsed!
                  isExpanded ? "h-8 max-w-[160px]" : "h-6 max-w-[40px]"
                )}
              />
            ) : (
              <div className="flex items-center gap-2 text-slate-900">
                <div className="h-8 w-8 bg-primary rounded-lg flex items-center justify-center shadow-sm shrink-0">
                  <Package2 className="h-5 w-5 text-white" />
                </div>
                {isExpanded && (
                  <span className="text-lg font-extrabold tracking-tight truncate">
                    {tenant?.name || "Naviera"}
                  </span>
                )}
              </div>
            )}
          </Link>
        </div>

        {/* NAVIGATION LINKS */}
        <nav
          className={cn(
            "flex-1 py-6 space-y-2 overflow-y-auto overflow-x-hidden",
            isExpanded ? "px-4" : "px-3"
          )}
        >
          {isExpanded && (
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-4 px-2 whitespace-nowrap">
              Main Menu
            </div>
          )}

          {navItems.map((item) => {
            const resolvedHref = routeTo(item.href);
            const isActive = checkIsActive(item.href);

            return (
              <Link
                key={item.name}
                href={resolvedHref}
                title={!isExpanded ? item.name : undefined}
                className={cn(
                  "flex items-center rounded-xl transition-all font-medium whitespace-nowrap",
                  isExpanded
                    ? "gap-3 px-3 py-2.5 text-sm"
                    : "justify-center h-12 w-12 mx-auto",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-100"
                )}
              >
                <item.icon
                  className={cn(
                    "shrink-0",
                    isExpanded ? "h-4 w-4" : "h-5 w-5",
                    isActive ? "text-primary-foreground" : "text-slate-500"
                  )}
                />

                <span
                  className={cn(
                    "transition-opacity duration-200",
                    isExpanded ? "opacity-100" : "opacity-0 w-0 hidden"
                  )}
                >
                  {item.name}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* COLLAPSE TOGGLE BUTTON */}
        <div className="p-4 border-t border-slate-800/60 bg-slate-950 flex justify-center shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="text-slate-400 hover:text-white hover:bg-slate-800 w-full rounded-xl h-10"
          >
            {isCollapsed ? (
              <ChevronRight className="h-5 w-5" />
            ) : (
              <ChevronLeft className="h-5 w-5" />
            )}
          </Button>
        </div>
      </aside>
    </>
  );
}
