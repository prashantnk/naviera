// src/app/[tenant_slug]/(app)/b2b/shipments/new/reverse/page.tsx
"use client";

/**
 * B2B reverse LR route.
 *
 * Reverse cargo bookings are switched off for the MVP (owner decision 2026-10-30,
 * WP0; the API rejects them too) and every entry point is hidden behind
 * `B2B_REVERSE_BOOKING_ENABLED`. A direct visit gets a plain-English notice with a
 * way forward. Re-enabling needs a Prime reverse quote, so the old wizard (built on
 * the retired rate engine) was removed rather than parked.
 */
import { Button } from "@/components/ui/button";
import { useTenant } from "@/components/providers/tenant-provider";
import { ArrowLeft, Building2 } from "lucide-react";
import Link from "next/link";

export default function B2BReverseBookingPage() {
  const { routeTo } = useTenant();
  return (
    <div className="max-w-xl mx-auto py-16 px-4" data-testid="b2b.reverse.unavailable">
      <div className="space-y-4 rounded-2xl border border-border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <Building2 className="h-6 w-6 text-primary" />
        </div>
        <h1 className="text-xl font-bold text-foreground">B2B returns are not available yet</h1>
        <p className="text-sm text-muted-foreground">
          Reverse cargo (B2B return) bookings are coming soon. To move goods back, book a new
          forward LR from the customer&apos;s location, or contact support.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="outline" asChild>
            <Link href={routeTo("/b2b/shipments")}>
              <ArrowLeft className="mr-2 h-4 w-4" /> Back to B2B orders
            </Link>
          </Button>
          <Button asChild>
            <Link href={routeTo("/b2b/shipments/new/forward")}>Book a forward LR</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
