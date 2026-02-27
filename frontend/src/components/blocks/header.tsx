// frontend/src/components/blocks/header.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase";
import { LayoutDashboard, LogOut, Menu, Package2, PhoneCall, UserCircle2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function Header() {
  const { tenant, routeTo } = useTenant();
  const brand = tenant?.settings?.brand;
  const contact = tenant?.settings?.contact;

  const params = useParams();
  const router = useRouter();
  const tenantSlug = (params?.tenant_slug as string) || "naviera";
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  // Check Auth State on Load
  useEffect(() => {
    const checkAuth = async () => {
      const supabase = getSupabaseClient(tenantSlug);
      const { data: { session } } = await supabase.auth.getSession();
      if (session) setIsLoggedIn(true);
    };
    checkAuth();
  }, [tenantSlug]);

  // 🔥 NEW: Handle Logout from Public Page
  const handleLogout = async () => {
    const supabase = getSupabaseClient(tenantSlug);
    await supabase.auth.signOut();
    setIsLoggedIn(false);
    // Refresh the page so the Hero Section also catches the logged-out state instantly!
    window.location.reload();
  };

  return (
    <>
      {tenant?.slug === 'logismart' && (
        <div className="w-full bg-[#dc2626] text-white text-xs md:text-sm font-semibold py-1.5 text-center tracking-wide">
          International Courier & Logistics Solutions Across World - Fast, Safe & Delivery on Time
        </div>
      )}

      <header className="sticky top-0 z-50 w-full border-b border-slate-200 bg-white shadow-sm">
        <div className="container mx-auto px-4 md:px-6 flex h-[72px] items-center justify-between">

          <Link href={routeTo("/")} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            {brand?.logo_url ? (
              <img src={brand.logo_url} alt={tenant!.name} className="h-10 md:h-12 object-contain" />
            ) : (
              <>
                <Package2 className="h-7 w-7 text-primary" />
                <span className="text-2xl font-extrabold tracking-tight text-slate-900">
                  {tenant?.name || "Naviera"}
                </span>
              </>
            )}
          </Link>

          <nav className="hidden lg:flex items-center gap-7 text-sm font-bold text-slate-700">
            <Link href={routeTo("/")} className="hover:text-primary transition-colors">Home</Link>
            <Link href={routeTo("/about")} className="hover:text-primary transition-colors">About Us</Link>
            <Link href={routeTo("/services")} className="hover:text-primary transition-colors">Services</Link>
            <Link href={routeTo("/track")} className="text-primary hover:text-primary/80 transition-colors">Track Shipment</Link>
            <Link href={routeTo("/contact")} className="hover:text-primary transition-colors">Contact Us</Link>
          </nav>

          <div className="hidden md:flex items-center gap-3">
            {contact?.phones && contact.phones.length > 0 && (
              <a href={`tel:${contact.phones[0].replace(/[^0-9+]/g, '')}`} className="hidden xl:flex items-center gap-2 text-sm font-bold text-slate-700 bg-slate-100 px-3 py-1.5 rounded-full border border-slate-200 hover:bg-slate-200 hover:text-primary transition-colors cursor-pointer mr-2">
                <PhoneCall className="h-4 w-4 text-primary" />
                {contact.phones[0]}
              </a>
            )}

            {/* 🔥 UPGRADED SMART AUTH BUTTONS */}
            {isLoggedIn ? (
              <>
                <Button variant="ghost" asChild className="font-semibold text-primary hidden lg:flex hover:text-primary hover:bg-primary/10">
                  <Link href={routeTo("/dashboard")}><LayoutDashboard className="h-4 w-4 mr-2" /> Dashboard</Link>
                </Button>
                {/* NEW LOGOUT BUTTON */}
                <Button variant="ghost" onClick={handleLogout} className="font-semibold text-slate-500 hidden lg:flex hover:text-red-600 hover:bg-red-50">
                  <LogOut className="h-4 w-4 mr-2" /> Logout
                </Button>
              </>
            ) : (
              <Button variant="outline" asChild className="font-bold text-slate-700 hidden lg:flex rounded-full px-6 border-slate-300 hover:bg-slate-100">
                <Link href={routeTo("/login")}><UserCircle2 className="h-4 w-4 mr-2" /> Login</Link>
              </Button>
            )}

            <Button asChild className="font-bold shadow-md rounded-full px-6 bg-[#dc2626] text-white hover:bg-[#b91c1c]">
              <Link href={routeTo("/shipments/new")}>Book Your Shipment</Link>
            </Button>
          </div>

          <Button variant="ghost" size="icon" className="lg:hidden">
            <Menu className="h-6 w-6 text-slate-900" />
          </Button>

        </div>
      </header>
    </>
  );
}