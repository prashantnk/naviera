// frontend/src/components/auth/capability-guard.tsx
"use client";

import Link from "next/link";
import { ShieldOff } from "lucide-react";

import { useUser } from "@/components/auth/auth-guard";
import type { CapabilityKey } from "@/components/auth/capabilities";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";

/** Where a blocked staff member is sent instead. */
const FALLBACK_HREF = "/dashboard";
const FALLBACK_LABEL = "Go to Home";

interface CapabilityGuardProps {
  /** Capability the user needs to open the route group. */
  capability: CapabilityKey;
  /** Plural name of the restricted area, e.g. "Remittances and invoices" (heading: "… aren't available for your role"). */
  area: string;
  /** One sentence telling the user why and who to ask. */
  reason: string;
  children: React.ReactNode;
}

/**
 * Renders `children` only for users holding `capability` (mirror of the backend
 * permission that would otherwise answer 403).
 *
 * Staff whose role cannot use a page and who open its URL directly (the menu
 * already hides it) get a clear explanation instead of a page that fails with a
 * raw "403" toast. The backend still enforces the permission; this is the UX layer.
 */
export function CapabilityGuard({ capability, area, reason, children }: CapabilityGuardProps) {
  const { capabilities } = useUser();
  const { routeTo } = useTenant();

  if (capabilities[capability]) return <>{children}</>;

  return (
    <div className="flex w-full flex-1 items-center justify-center p-6">
      <div
        data-testid="capability-guard.blocked"
        className="max-w-md space-y-4 rounded-2xl border border-border bg-card p-8 text-center shadow-sm"
      >
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <ShieldOff className="h-6 w-6 text-primary" />
        </div>
        <h2 className="text-xl font-bold text-foreground">{area} aren&apos;t available for your role</h2>
        <p className="text-sm text-muted-foreground">{reason}</p>
        <Button asChild>
          <Link href={routeTo(FALLBACK_HREF)}>{FALLBACK_LABEL}</Link>
        </Button>
      </div>
    </div>
  );
}
