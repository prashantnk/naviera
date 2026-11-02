// frontend/src/components/auth/flow-access-guard.tsx
"use client";

import Link from "next/link";
import { Clock, ShieldAlert, Truck } from "lucide-react";
import { useState } from "react";

import { useUser } from "@/components/auth/auth-guard";
import { RequestB2bAccessDialog } from "@/components/blocks/request-b2b-dialog";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";

/** Which business flow a route group belongs to. */
export type GuardedFlow = "B2C" | "B2B";

/** Copy + fallback destination for each guarded flow. */
const FLOW_GUARD_COPY: Record<GuardedFlow, { name: string; fallbackHref: string; fallbackLabel: string }> = {
  B2B: {
    name: "B2B Cargo",
    fallbackHref: "/dashboard",
    fallbackLabel: "Go to B2C Express",
  },
  B2C: {
    name: "B2C Express",
    fallbackHref: "/b2b/dashboard",
    fallbackLabel: "Go to B2B Cargo",
  },
};

interface FlowAccessGuardProps {
  flow: GuardedFlow;
  children: React.ReactNode;
}

/**
 * Blocks direct URL access to a flow the merchant's service scope does not
 * include (e.g. a B2C-only seller opening `/b2b/shipments/new/forward`).
 *
 * The menu already hides those links; this closes the deep-link gap. Admins and
 * owners always pass (`canAccessB2C` / `canAccessB2B` are true for them).
 */
export function FlowAccessGuard({ flow, children }: FlowAccessGuardProps) {
  const { canAccessB2B, canAccessB2C, user } = useUser();
  const { routeTo } = useTenant();
  const [requestB2bOpen, setRequestB2bOpen] = useState(false);
  const allowed = flow === "B2B" ? canAccessB2B : canAccessB2C;
  const isB2bPending = user?.b2b_request_status === "PENDING";

  if (allowed) return <>{children}</>;

  const copy = FLOW_GUARD_COPY[flow];
  return (
    <div className="flex w-full flex-1 items-center justify-center p-6">
      <div className="max-w-md space-y-4 rounded-2xl border border-border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <ShieldAlert className="h-6 w-6 text-primary" />
        </div>
        <h2 className="text-xl font-bold text-foreground">
          {copy.name} isn&apos;t enabled for your account
        </h2>
        <p className="text-sm text-muted-foreground">
          {flow === "B2B"
            ? isB2bPending
              ? "Your B2B Heavy Cargo request is awaiting Admin review. You can update your optional GSTIN or PAN anytime."
              : "Request B2B Heavy Cargo access (with optional GSTIN or PAN) or ask an Admin to approve your account."
            : `Ask your account manager to enable ${copy.name} if you need it.`}
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-2.5 pt-1">
          {flow === "B2B" && (
            <Button
              type="button"
              onClick={() => setRequestB2bOpen(true)}
              className="gap-1.5"
            >
              {isB2bPending ? (
                <>
                  <Clock className="h-4 w-4" />
                  Update B2B Request
                </>
              ) : (
                <>
                  <Truck className="h-4 w-4" />
                  Request B2B Cargo Access
                </>
              )}
            </Button>
          )}
          <Button asChild variant={flow === "B2B" ? "outline" : "default"}>
            <Link href={routeTo(copy.fallbackHref)}>{copy.fallbackLabel}</Link>
          </Button>
        </div>
      </div>

      {flow === "B2B" && (
        <RequestB2bAccessDialog
          open={requestB2bOpen}
          onOpenChange={setRequestB2bOpen}
        />
      )}
    </div>
  );
}
