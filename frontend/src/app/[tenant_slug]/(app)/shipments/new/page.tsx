// frontend/src/app/[tenant_slug]/(app)/shipments/new/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export { CATEGORY_LABELS } from "./_components/forward-form-step";

export default function LegacyCreateShipmentRedirect() {
  const { routeTo } = useTenant();
  const router = useRouter();

  useEffect(() => {
    router.replace(routeTo("/shipments/new/forward"));
  }, [router, routeTo]);

  return (
    <div className="flex h-[60vh] items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );
}
