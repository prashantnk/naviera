// frontend/src/components/blocks/app-sidebar.tsx
"use client";

import { NavMenu } from "@/components/blocks/nav-menu";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWorkspaceFlow } from "@/components/providers/workspace-flow-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { FLOW_DASHBOARD_HREF } from "@/lib/workspace-flow";
import { ChevronLeft, ChevronRight, Package2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export function AppSidebar() {
  const { tenant, routeTo } = useTenant();
  const brand = tenant?.settings?.brand;

  const [isCollapsed, setIsCollapsed] = useState(true);
  const [isHovered, setIsHovered] = useState(false);

  // Sidebar is expanded if it's NOT collapsed, OR if the user is hovering over it.
  const isExpanded = !isCollapsed || isHovered;
  const { activeFlow } = useWorkspaceFlow();

  return (
    <>
      <div
        className={cn(
          "hidden md:block shrink-0 transition-[width] duration-300 ease-in-out z-0",
          isCollapsed ? "w-[72px]" : "w-64"
        )}
      />

      <aside
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={cn(
          "bg-slate-950 fixed left-0 top-0 bottom-0 hidden md:flex flex-col border-r border-slate-800 z-50 transition-all duration-300 ease-in-out overflow-hidden",
          isExpanded ? "w-64" : "w-[72px]",
          isCollapsed && isHovered ? "shadow-2xl" : ""
        )}
      >
        <div className="h-16 flex items-center justify-center px-3 border-b border-slate-200 bg-white shrink-0">
          <Link
            href={routeTo(FLOW_DASHBOARD_HREF[activeFlow])}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity w-full overflow-hidden justify-center"
          >
            {brand?.logo_url ? (
              <img
                src={brand.logo_url}
                alt={tenant?.name}
                className={cn(
                  "object-contain transition-all duration-300",
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

        {/* NAVIGATION — grouped Delhivery-style menu for the active flow */}
        <nav
          className={cn(
            "flex-1 py-3 overflow-y-auto overflow-x-hidden [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]",
            isExpanded ? "px-3" : "px-2"
          )}
        >
          <NavMenu isExpanded={isExpanded} />
        </nav>

        {/* COLLAPSE TOGGLE BUTTON */}
        <div className="p-2.5 border-t border-slate-800/60 bg-slate-950 flex justify-center shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="text-slate-400 hover:text-white hover:bg-slate-800 w-full rounded-xl h-9"
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </Button>
        </div>
      </aside>
    </>
  );
}
