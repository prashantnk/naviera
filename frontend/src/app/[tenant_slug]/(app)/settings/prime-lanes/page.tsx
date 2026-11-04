// frontend/src/app/[tenant_slug]/(app)/settings/prime-lanes/page.tsx
"use client";

/**
 * Staff page: Logismart Prime lanes (and, for staff who cannot open Workspace
 * Settings, a read-only view of the pricing policy).
 *
 * Owner/admin edit here and in Workspace Settings ▸ Pricing; operations, support
 * and read-only staff see the same data without edit controls. Customers are
 * refused (the backend also returns 403).
 */
import { ArrowLeft, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { useUser } from "@/components/auth/auth-guard";
import { PricingPolicyPanel } from "@/components/pricing-admin/pricing-policy-panel";
import { PrimeLanesEditor } from "@/components/pricing-admin/prime-lanes-editor";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";

/** Renders the Prime lanes page. */
export default function PrimeLanesPage() {
  const { tenantSlug, routeTo } = useTenant();
  const { capabilities } = useUser();
  const canEdit = capabilities.canManageSettings;

  if (!capabilities.isStaff) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center space-y-4 text-center">
        <ShieldAlert className="h-16 w-16 text-rose-500" />
        <h2 className="text-2xl font-bold text-slate-900">Access Denied</h2>
        <p className="max-w-md text-sm text-slate-500">Only Logismart staff can see Prime lanes.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 pb-16 md:px-6" data-testid="prime-lanes.page">
      <div className="flex flex-col gap-3 border-b border-slate-200 pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 md:text-3xl">Pricing &amp; Prime lanes</h1>
          <p className="mt-1 text-sm text-slate-500">
            Transporter rates behind &ldquo;Logismart Prime&rdquo; (B2B cargo). Delhivery prices come live
            from Delhivery.
          </p>
        </div>
        {canEdit && (
          <Button variant="outline" size="sm" asChild className="bg-white">
            <Link href={routeTo("/settings")} prefetch={true} data-testid="prime-lanes.back-to-settings">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Markups &amp; COD fee: Workspace Settings ▸ Pricing
            </Link>
          </Button>
        )}
      </div>

      {!canEdit && <PricingPolicyPanel tenantSlug={tenantSlug} canEdit={false} />}
      <PrimeLanesEditor tenantSlug={tenantSlug} canEdit={canEdit} />
    </div>
  );
}
