// frontend/src/app/[tenant_slug]/(app)/b2b/shipments/page.tsx
"use client";

import { OrdersWorkspace } from "@/components/pickups/orders-workspace";
import { ServiceFlow } from "@/lib/workspace-flow";
import { Suspense } from "react";

/**
 * B2B "B2B Orders" page (Delhivery One layout), same workspace as B2C with
 * cargo copy (LRN, box count, freight payment mode).
 *
 * `useSearchParams` (status deep links) must render inside `<Suspense>`.
 */
export default function B2BShipmentsDashboard() {
  return (
    <Suspense fallback={null}>
      <OrdersWorkspace flow={ServiceFlow.B2B} />
    </Suspense>
  );
}
