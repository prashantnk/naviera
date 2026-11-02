// frontend/src/app/[tenant_slug]/(app)/b2b/pickup-requests/page.tsx
"use client";

import { ServiceFlow } from "@/api_client";
import { PickupRequestsList } from "@/components/pickups/pickup-requests-list";

/**
 * B2B (Surface) Pickup Requests list. Same Delhivery layout as B2C; the B2B
 * extras (LRN wording, blind pickups, driver run-sheet / Manifest Copy and the
 * Admin "Mark picked up" outcome) come from the shared flow-aware component.
 */
export default function B2BPickupRequestsPage() {
  return <PickupRequestsList serviceFlow={ServiceFlow.B2B} />;
}
