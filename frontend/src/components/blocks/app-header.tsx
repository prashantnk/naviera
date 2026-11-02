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
import { signOutAndRedirect } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import {
  BookOpenCheck,
  Building2,
  CheckCircle2,
  Globe,
  LogOut,
  MapPin,
  Menu,
  Package2,
  Settings,
  ShieldCheck,
  UserPen,
  Users,
  X,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useUser } from "@/components/auth/auth-guard";
import { ServiceScope, UserRole } from "@/api_client";
import { WalletHeaderPill } from "@/components/wallet/wallet-header-pill";
import { FlowSwitcher } from "@/components/blocks/flow-switcher";
import { QuickActionsMenu } from "@/components/blocks/quick-actions-menu";
import { NavMenu } from "@/components/blocks/nav-menu";
import { ProfileDialog } from "@/components/blocks/profile-dialog";
import { AdminCoordinationGuideModal } from "@/components/blocks/admin-coordination-guide-modal";
import { getInitials } from "@/lib/initials";

export function AppHeader() {
  const { routeTo, tenantSlug, tenant } = useTenant();
  const brand = tenant?.settings?.brand;

  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isGuideOpen, setIsGuideOpen] = useState(false);

  const handleLogout = async () => {
    await signOutAndRedirect(tenantSlug, routeTo("/login"));
  };

  const { user, capabilities, serviceScope } = useUser();

  const userDisplayName = user?.full_name?.trim()
    ? user.full_name.trim()
    : user?.email
    ? user.email
        .split("@")[0]
        .replace(/[._-]+/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase())
    : "Account User";

  const userInitials = getInitials(user?.full_name, user?.email);

  const roleLabel =
    user?.role === UserRole.OWNER
      ? "Workspace Owner"
      : user?.role === UserRole.ADMIN
        ? "Admin"
        : user?.role === UserRole.OPERATIONS_USER
          ? "Operations-User"
          : user?.role === UserRole.SUPPORT_USER
            ? "Support-User"
            : user?.role === UserRole.READ_ONLY_USER
              ? "Read access Only-User"
              : "Customer";

  const scopeLabel =
    serviceScope === ServiceScope.BOTH
      ? "Unified (B2C + B2B)"
      : serviceScope === ServiceScope.B2B
        ? "B2B Heavy Cargo"
        : "B2C Express";

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-2.5 sm:px-4 md:px-6 sticky top-0 z-40 shadow-sm">
      <div className="flex md:hidden items-center mr-1 sm:mr-2 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Open navigation menu"
          onClick={() => setIsMobileMenuOpen(true)}
        >
          <Menu className="h-5 w-5 text-slate-600" />
        </Button>
      </div>

      {/* Spacer keeps actions right-aligned now that the tracking search is removed */}
      <div className="flex-1 min-w-0" />

      {/* USER ACTIONS */}
      <div className="flex items-center gap-1.5 sm:gap-3 shrink-0 ml-1 sm:ml-4">
        <QuickActionsMenu />

        <WalletHeaderPill />

        {/* STAFF DELHIVERY CO-ORDINATION GUIDE */}
        {capabilities.isStaff && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setIsGuideOpen(true)}
            data-testid="header-delhivery-guide-btn"
            className="hidden sm:flex h-9 border-slate-200 text-slate-700 hover:text-primary font-semibold"
          >
            <BookOpenCheck className="mr-1.5 h-4 w-4 text-primary" />
            Delhivery Guide
          </Button>
        )}

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

        {/* FLOW SWITCHER (B2C Express ⇄ B2B Cargo) — beside the profile, like Delhivery One */}
        <FlowSwitcher variant="header" />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="My Account"
              className="h-9 px-1.5 sm:px-2.5 rounded-full bg-slate-100 border border-slate-200 flex items-center gap-2 text-slate-700 cursor-pointer hover:bg-primary/10 hover:text-primary hover:border-primary/20 transition-colors shadow-2xs"
            >
              <div className="h-6 w-6 rounded-full bg-primary/15 text-primary flex items-center justify-center text-[11px] font-bold shrink-0">
                {userInitials}
              </div>
              <span className="hidden lg:inline-block text-xs font-semibold max-w-[120px] truncate">
                {userDisplayName}
              </span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-72 sm:w-80 rounded-2xl shadow-xl border-slate-200 p-2"
          >
            <DropdownMenuLabel className="p-3 bg-slate-50 rounded-xl border border-slate-100 mb-1.5 font-normal">
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm font-bold shadow-sm shrink-0">
                  {userInitials}
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-bold text-slate-900 truncate">
                      {userDisplayName}
                    </p>
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-full shrink-0">
                      <CheckCircle2 className="h-2.5 w-2.5" />
                      Active
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 break-all leading-snug">
                    {user?.email || "Authenticated User"}
                  </p>
                </div>
              </div>

              <div className="mt-3 pt-2.5 border-t border-slate-200/80 grid grid-cols-2 gap-2 text-[11px]">
                <div className="bg-white rounded-lg p-2 border border-slate-100">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 block">
                    Role
                  </span>
                  <span className="font-bold text-slate-800 flex items-center gap-1 mt-0.5 truncate">
                    <ShieldCheck className="h-3 w-3 text-primary shrink-0" />
                    {roleLabel}
                  </span>
                </div>
                <div className="bg-white rounded-lg p-2 border border-slate-100">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 block">
                    Service Scope
                  </span>
                  <span className="font-bold text-slate-800 block mt-0.5 truncate">
                    {scopeLabel}
                  </span>
                </div>
              </div>

              <div className="mt-2 bg-white rounded-lg px-2.5 py-1.5 border border-slate-100 flex items-center justify-between text-xs">
                <span className="text-slate-400 font-medium flex items-center gap-1.5">
                  <Building2 className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                  Workspace
                </span>
                <span className="font-bold text-slate-800 truncate max-w-[160px]">
                  {tenant?.name || tenantSlug}
                </span>
              </div>
            </DropdownMenuLabel>

            <DropdownMenuItem
              className="cursor-pointer rounded-lg py-2"
              onSelect={() => setIsProfileOpen(true)}
            >
              <UserPen className="mr-2.5 h-4 w-4 text-slate-500" />
              <span>My profile</span>
            </DropdownMenuItem>

            <DropdownMenuItem asChild className="cursor-pointer rounded-lg py-2">
              <Link href={routeTo("/wallet")} className="flex items-center">
                <Wallet className="mr-2.5 h-4 w-4 text-slate-500" />
                <span>Wallet & Billing Ledger</span>
              </Link>
            </DropdownMenuItem>

            <DropdownMenuItem asChild className="cursor-pointer rounded-lg py-2">
              <Link href={routeTo("/address-book")} className="flex items-center">
                <MapPin className="mr-2.5 h-4 w-4 text-slate-500" />
                <span>Saved Address Book</span>
              </Link>
            </DropdownMenuItem>

            {capabilities.canManageTeam && (
              <DropdownMenuItem asChild className="cursor-pointer rounded-lg py-2">
                <Link href={routeTo("/team")} className="flex items-center">
                  <Users className="mr-2.5 h-4 w-4 text-slate-500" />
                  <span>Team & Role Scopes</span>
                </Link>
              </DropdownMenuItem>
            )}
            {capabilities.canManageSettings && (
              <DropdownMenuItem asChild className="cursor-pointer rounded-lg py-2">
                <Link href={routeTo("/settings")} className="flex items-center">
                  <Settings className="mr-2.5 h-4 w-4 text-slate-500" />
                  <span>Workspace Settings</span>
                </Link>
              </DropdownMenuItem>
            )}

            <DropdownMenuItem asChild className="cursor-pointer rounded-lg py-2 md:hidden">
              <Link href={routeTo("/")} className="flex items-center">
                <Globe className="mr-2.5 h-4 w-4 text-slate-500" />
                <span>Public Website</span>
              </Link>
            </DropdownMenuItem>

            <DropdownMenuSeparator className="my-1" />
            <DropdownMenuItem
              className="text-red-600 cursor-pointer font-semibold focus:text-red-700 focus:bg-red-50 rounded-lg py-2"
              onClick={handleLogout}
            >
              <LogOut className="mr-2.5 h-4 w-4" />
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

            <div className="px-4 pt-4 shrink-0">
              <FlowSwitcher variant="drawer" />
            </div>

            <nav className="flex-1 py-4 px-4 overflow-y-auto">
              <NavMenu isExpanded onNavigate={() => setIsMobileMenuOpen(false)} />
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
      <ProfileDialog open={isProfileOpen} onOpenChange={setIsProfileOpen} />
      {capabilities.isStaff && (
        <AdminCoordinationGuideModal open={isGuideOpen} onOpenChange={setIsGuideOpen} />
      )}
    </header>
  );
}
