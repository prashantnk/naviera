// src/components/blocks/header.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Menu, Package2 } from "lucide-react";
import Link from "next/link";

export function Header() {
  const { tenant, routeTo } = useTenant();
  const tenantName = tenant?.name || "Naviera";

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/60">
      <div className="container mx-auto px-4 md:px-6 flex h-16 items-center justify-between">

        {/* Brand Logo */}
        <Link href={routeTo("/")} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <Package2 className="h-6 w-6 text-primary" />
          <span className="text-xl font-bold tracking-tight text-slate-900">
            {tenantName}
          </span>
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-6 text-sm font-medium text-slate-600">
          <Link href={routeTo("/")} className="hover:text-primary transition-colors">Home</Link>
          <Link href={routeTo("/track")} className="hover:text-primary transition-colors font-semibold">Track Shipment</Link>
          <Link href="#" className="hover:text-primary transition-colors">Services</Link>
          <Link href="#" className="hover:text-primary transition-colors">Solutions</Link>
        </nav>

        {/* Actions (App Access) */}
        <div className="hidden md:flex items-center gap-4">
          <Button variant="ghost" asChild>
            <Link href={routeTo("/dashboard")}>Dashboard</Link>
          </Button>
          <Button asChild>
            <Link href={routeTo("/shipments/new")}>Book Shipment</Link>
          </Button>
        </div>

        {/* Mobile Menu Toggle */}
        <Button variant="ghost" size="icon" className="md:hidden">
          <Menu className="h-5 w-5" />
          <span className="sr-only">Toggle menu</span>
        </Button>

      </div>
    </header>
  );
}