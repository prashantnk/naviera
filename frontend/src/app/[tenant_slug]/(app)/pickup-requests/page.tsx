// frontend/src/app/[tenant_slug]/(app)/pickup-requests/page.tsx
"use client";

import { ServiceFlow } from "@/api_client";
import { PickupRequestsList } from "@/components/pickups/pickup-requests-list";

/** B2C (Domestic) Pickup Requests list. */
export default function B2CPickupRequestsPage() {
  return <PickupRequestsList serviceFlow={ServiceFlow.B2C} />;
}
