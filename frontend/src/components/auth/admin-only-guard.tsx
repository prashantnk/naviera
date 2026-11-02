// frontend/src/components/auth/admin-only-guard.tsx
"use client";

import Link from "next/link";
import { Lock } from "lucide-react";

import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";

interface AdminOnlyGuardProps {
  /** Short description of what is restricted, e.g. "Editing shipments". */
  action: string;
  /** Where a non-admin is sent instead (tenant-relative path). */
  backHref: string;
  /** Label for the back button. */
  backLabel: string;
  children: React.ReactNode;
}

/**
 * Renders `children` only for roles that may edit shipments
 * (`capabilities.canOperate || capabilities.canBook`: owner, admin, operations
 * user, and customers editing their own live orders per plan B9 / Delhivery One
 * `update-forward-order`).
 *
 * Support and Read-Only staff who open `/shipments/{id}/edit` directly see a
 * clear explanation instead of a full form that fails with 403 on save.
 * The backend still enforces per-field and status permissions (`assert_edit_allowed`).
 */
export function AdminOnlyGuard({ action, backHref, backLabel, children }: AdminOnlyGuardProps) {
  const { capabilities } = useUser();
  const { routeTo } = useTenant();

  if (capabilities.canOperate || capabilities.canBook) return <>{children}</>;

  return (
    <div className="flex w-full flex-1 items-center justify-center p-6">
      <div className="max-w-md space-y-4 rounded-2xl border border-border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <Lock className="h-6 w-6 text-primary" />
        </div>
        <h2 className="text-xl font-bold text-foreground">{action} isn&apos;t available for your role</h2>
        <p className="text-sm text-muted-foreground">
          Read-Only and Support staff can view shipments, but only the merchant or operations team can edit shipment details.
        </p>
        <Button asChild>
          <Link href={routeTo(backHref)}>{backLabel}</Link>
        </Button>
      </div>
    </div>
  );
}
