// frontend/src/app/[tenant_slug]/(app)/shipments/page.tsx
"use client";

import { OrdersWorkspace } from "@/components/pickups/orders-workspace";
import { ServiceFlow } from "@/lib/workspace-flow";
import { Suspense } from "react";

/**
 * B2C "Orders" page (Delhivery One layout). The shared workspace owns the
 * status rail, filters, grid and "Add to pickup" selection.
 *
 * `useSearchParams` (status deep links) must render inside `<Suspense>`.
 */
export default function ShipmentsPage() {
  return (
    <Suspense fallback={null}>
      <OrdersWorkspace flow={ServiceFlow.B2C} />
    </Suspense>
  );
}
