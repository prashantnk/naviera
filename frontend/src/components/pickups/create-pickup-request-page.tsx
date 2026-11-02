// frontend/src/components/pickups/create-pickup-request-page.tsx
"use client";

/**
 * Route-level wrapper for the Create Pickup Request form. Reads the prefill
 * query params (`location`, `location_name`, `shipments`, `date`) and wraps
 * `useSearchParams` in `<Suspense>` as required for production builds.
 */
import { ServiceFlow } from "@/api_client";
import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { CreatePickupRequestForm } from "./create-pickup-request-form";
import { PICKUP_QUERY_PARAMS, SHIPMENT_IDS_SEPARATOR } from "./pickup-constants";

/** Reads prefill params and renders the form (must sit inside `<Suspense>`). */
function CreatePickupRequestFromQuery({ serviceFlow }: { serviceFlow: ServiceFlow }) {
  const searchParams = useSearchParams();
  const locationId = searchParams.get(PICKUP_QUERY_PARAMS.location) ?? undefined;
  const locationName = searchParams.get(PICKUP_QUERY_PARAMS.locationName) ?? undefined;
  const date = searchParams.get(PICKUP_QUERY_PARAMS.date) ?? undefined;
  const shipmentIds = (searchParams.get(PICKUP_QUERY_PARAMS.shipments) ?? "")
    .split(SHIPMENT_IDS_SEPARATOR)
    .map((id) => id.trim())
    .filter(Boolean);

  return (
    <CreatePickupRequestForm
      key={searchParams.toString()}
      serviceFlow={serviceFlow}
      initialLocationId={locationId}
      initialLocationName={locationName}
      initialShipmentIds={shipmentIds}
      initialDate={date}
    />
  );
}

/** Shared page body for `/pickup-requests/new` and `/b2b/pickup-requests/new`. */
export function CreatePickupRequestPage({ serviceFlow }: { serviceFlow: ServiceFlow }) {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      }
    >
      <CreatePickupRequestFromQuery serviceFlow={serviceFlow} />
    </Suspense>
  );
}
