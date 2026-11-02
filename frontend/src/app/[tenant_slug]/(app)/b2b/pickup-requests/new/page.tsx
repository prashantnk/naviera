// frontend/src/app/[tenant_slug]/(app)/b2b/pickup-requests/new/page.tsx
"use client";

import { ServiceFlow } from "@/api_client";
import { CreatePickupRequestPage } from "@/components/pickups/create-pickup-request-page";

/**
 * B2B (Surface) Create Pickup Request: shared form with the B2B extras
 * (blind pickup + declared box count, 2 PM same-day cut-off note).
 */
export default function NewB2BPickupRequestPage() {
  return <CreatePickupRequestPage serviceFlow={ServiceFlow.B2B} />;
}
