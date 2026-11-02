// frontend/src/components/dashboard/dashboard-right-rail.tsx
"use client";

import { ServiceFlow } from "@/lib/workspace-flow";

import { ExploreServicesCard } from "./explore-services-card";
import { DashboardResourcesCard } from "./resources-card";
import { DashboardSupportCard } from "./support-card";
import { DashboardWalletCard } from "./wallet-card";

/**
 * Right rail shared by the B2C and B2B home dashboards (stacks below the
 * main column on mobile): Support, Wallet, Resources, Explore other services
 * (Delhivery One order).
 */
export function DashboardRightRail({ flow }: { flow: ServiceFlow }) {
  return (
    <aside aria-label="Account shortcuts" className="min-w-0 space-y-4">
      <DashboardSupportCard />
      <DashboardWalletCard flow={flow} />
      <DashboardResourcesCard flow={flow} />
      <ExploreServicesCard flow={flow} />
    </aside>
  );
}
