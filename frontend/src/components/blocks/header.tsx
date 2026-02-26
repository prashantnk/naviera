// src/components/blocks/header.tsx
"use client"; // <-- It's interactive (mobile menu), so it must be a client component

import { useTenant } from "@/components/providers/tenant-provider"; // <-- Import our global hook
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu, Package2, Search } from "lucide-react";
import Link from "next/link";

export function Header() {
  // 🔥 NO PROPS! We pull exactly what we need from the Global Context
  const { tenant, routeTo } = useTenant();

  // Fallback to "Naviera" if tenant is missing
  const tenantName = tenant?.name || "Naviera";

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/60">
      <div className="container mx-auto px-4 md:px-6 flex h-16 items-center justify-between">

        <div className="flex items-center gap-2">
          <Package2 className="h-6 w-6 text-primary" />
          <span className="text-xl font-bold tracking-tight text-slate-900">
            {tenantName}
          </span>
        </div>

        <nav className="hidden md:flex items-center gap-6 text-sm font-medium text-slate-600">
          <Link href="#" className="hover:text-primary transition-colors">Home</Link>
          <Link href="#" className="hover:text-primary transition-colors">Services</Link>
          <Link href="#" className="hover:text-primary transition-colors">Solutions</Link>
          <Link href="#" className="hover:text-primary transition-colors">Support</Link>
        </nav>

        <div className="hidden md:flex items-center gap-4">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              type="text"
              placeholder="Track Order..."
              className="w-56 pl-9 bg-slate-50 border-transparent focus-visible:bg-white"
            />
          </div>
          <Button asChild>
            {/* Safe routing using global tenantSlug */}
            <Link href={routeTo("/login")}>Book Shipment</Link>
          </Button>
        </div>

        {/* Mobile Menu Toggle (Needs useState to actually open/close in the future) */}
        <Button variant="ghost" size="icon" className="md:hidden">
          <Menu className="h-5 w-5" />
          <span className="sr-only">Toggle menu</span>
        </Button>

      </div>
    </header>
  );
}