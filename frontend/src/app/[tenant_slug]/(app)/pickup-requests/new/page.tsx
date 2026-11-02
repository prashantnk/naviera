// frontend/src/app/[tenant_slug]/(app)/pickup-requests/new/page.tsx
"use client";

import { ServiceFlow } from "@/api_client";
import { CreatePickupRequestPage } from "@/components/pickups/create-pickup-request-page";

/** B2C (Domestic) Create Pickup Request. */
export default function NewB2CPickupRequestPage() {
  return <CreatePickupRequestPage serviceFlow={ServiceFlow.B2C} />;
}
