// frontend/src/components/blocks/app-header.tsx
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
import { cn } from "@/lib/utils";
import {
  Bell,
  Globe,
  Home,
  LogOut,
  MapPin,
  Menu,
  Package,
  Package2,
  PlusCircle,
  Search,
  Settings,
  User,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

export function AppHeader() {
  const { routeTo, tenantSlug, tenant } = useTenant();
  const router = useRouter();
  const pathname = usePathname();
  const brand = tenant?.settings?.brand;
  const supabase = getSupabaseClient(tenantSlug);

  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const handleLogout = async () => {
    await supabase.auth.signOut();
    router.push(routeTo("/login"));
  };

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
    if (
      href === "/shipments" &&
      pathname.startsWith(`${resolvedHref}/`) &&
      !pathname.includes("/new")
    )
      return true;
    return false;
  };

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-4 md:px-6 sticky top-0 z-40 shadow-sm">
      <div className="flex md:hidden items-center mr-2 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsMobileMenuOpen(true)}
        >
          <Menu className="h-5 w-5 text-slate-600" />
        </Button>
      </div>

      <div className="flex items-center flex-1 max-w-md">
        <div className="relative w-full group">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 group-focus-within:text-primary transition-colors" />
          <Input
            type="text"
            placeholder="Search Tracking ID..."
            className="w-full pl-9 pr-12 bg-slate-100/50 border-slate-200 focus-visible:bg-white focus-visible:ring-primary h-9 rounded-lg text-sm shadow-inner transition-all"
          />
          <div className="absolute right-2 top-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1 pointer-events-none">
            <kbd className="inline-flex h-5 items-center gap-1 rounded border bg-white px-1.5 font-mono text-[10px] font-medium text-slate-400 shadow-sm">
              <span className="text-xs">⌘</span>K
            </kbd>
          </div>
        </div>
      </div>

      {/* 🔥 USER ACTIONS */}
      <div className="flex items-center gap-3 shrink-0 ml-4">
        {/* EXPOSED PUBLIC WEBSITE LINK */}
        <Button
          variant="outline"
          size="sm"
          asChild
          className="hidden md:flex h-9 border-slate-200 text-slate-600 hover:text-primary"
        >
          <Link href={routeTo("/")}>
            <Globe className="mr-2 h-4 w-4" />
            Public Website
          </Link>
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="text-slate-500 hidden sm:flex h-9 w-9 rounded-full hover:bg-slate-100"
        >
          <Bell className="h-4 w-4" />
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <div className="h-9 w-9 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-600 cursor-pointer hover:bg-primary/10 hover:text-primary transition-colors shadow-sm">
              <User className="h-4 w-4" />
            </div>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-56 rounded-xl shadow-lg"
          >
            <DropdownMenuLabel className="font-semibold text-slate-800">
              My Account
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-red-600 cursor-pointer font-medium focus:text-red-700 focus:bg-red-50"
              onClick={handleLogout}
            >
              <LogOut className="mr-2 h-4 w-4" />
              <span>Log out</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* MOBILE SLIDE-OUT DRAWER */}
      {isMobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-300"
            onClick={() => setIsMobileMenuOpen(false)}
          />
          <div className="relative w-72 bg-slate-950 h-full flex flex-col shadow-2xl animate-in slide-in-from-left duration-300 border-r border-slate-800">
            <div className="h-16 flex items-center justify-between px-6 border-b border-slate-800/60 bg-slate-950/50 shrink-0">
              {brand?.logo_url ? (
                <div className="bg-white p-1 rounded-md w-full max-w-[120px] flex items-center justify-start">
                  <img
                    src={brand.logo_url}
                    alt={tenant?.name}
                    className="h-5 object-contain"
                  />
                </div>
              ) : (
                <div className="flex items-center gap-2 text-white">
                  <Package2 className="h-5 w-5 text-primary" />
                  <span className="text-base font-bold tracking-tight truncate">
                    {tenant?.name || "Naviera"}
                  </span>
                </div>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="text-slate-400 hover:text-white h-8 w-8"
                onClick={() => setIsMobileMenuOpen(false)}
              >
                <X className="h-5 w-5" />
              </Button>
            </div>

            <nav className="flex-1 py-6 px-4 space-y-1.5 overflow-y-auto">
              <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4 px-2">
                Menu
              </div>
              {navItems.map((item) => {
                const isActive = checkIsActive(item.href);
                return (
                  <Link
                    key={item.name}
                    href={routeTo(item.href)}
                    onClick={() => setIsMobileMenuOpen(false)}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-sm font-medium",
                      isActive
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-100"
                    )}
                  >
                    <item.icon
                      className={cn(
                        "h-4 w-4",
                        isActive ? "text-primary-foreground" : "text-slate-500"
                      )}
                    />
                    {item.name}
                  </Link>
                );
              })}
            </nav>

            {/* MOBILE PUBLIC LINK */}
            <div className="p-4 border-t border-slate-800/60 bg-slate-900/20">
              <Link
                href={routeTo("/")}
                onClick={() => setIsMobileMenuOpen(false)}
                className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-slate-800/80 transition-all group"
              >
                <div className="h-9 w-9 rounded-md bg-slate-800 flex items-center justify-center text-slate-400 group-hover:text-primary-foreground group-hover:bg-primary transition-colors shrink-0 shadow-inner">
                  <Globe className="h-4 w-4" />
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="text-sm font-semibold text-slate-200 truncate">
                    Public Website
                  </span>
                </div>
              </Link>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
