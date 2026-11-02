// frontend/src/app/[tenant_slug]/(app)/delivery-exceptions/page.tsx
"use client";

import { Suspense } from "react";
import { Loader2 } from "lucide-react";

import { ServiceFlow } from "@/api_client";
import { ExceptionsWorkspace } from "@/components/exceptions/exceptions-workspace";

export default function B2CDeliveryExceptionsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[50vh] items-center justify-center">
          <Loader2 className="size-7 animate-spin text-primary" />
        </div>
      }
    >
      <ExceptionsWorkspace serviceFlow={ServiceFlow.B2C} />
    </Suspense>
  );
}
