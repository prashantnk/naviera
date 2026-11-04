// frontend/src/components/dashboard/resources-card.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { ServiceFlow } from "@/lib/workspace-flow";
import { BookOpen, Calculator, ChevronRight, ExternalLink, MapPin, type LucideIcon } from "lucide-react";
import Link from "next/link";

/** Rate calculator route for each flow. */
const RATE_CALCULATOR_HREF: Record<ServiceFlow, string> = {
  [ServiceFlow.B2C]: "/rate-calculator",
  [ServiceFlow.B2B]: "/b2b/rate-calculator",
};

/** Public (unauthenticated) tracking portal. */
const PUBLIC_TRACKING_HREF = "/track";

interface ResourceLinkProps {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Opens in a new tab (used for the public, non-app tracking page). */
  isExternal?: boolean;
}

/** One row in the Resources card. */
function ResourceLink({ href, label, icon: Icon, isExternal = false }: ResourceLinkProps) {
  return (
    <Link
      href={href}
      prefetch={isExternal ? false : true}
      target={isExternal ? "_blank" : undefined}
      rel={isExternal ? "noopener noreferrer" : undefined}
      className="group flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5 text-sm font-medium text-foreground outline-none transition-colors hover:bg-primary/5 active:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-secondary/10">
        <Icon className="h-4 w-4 text-secondary" aria-hidden />
      </span>
      <span className="flex-1">{label}</span>
      {isExternal ? (
        <>
          <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </>
      ) : (
        <ChevronRight
          className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5"
          aria-hidden
        />
      )}
    </Link>
  );
}

/**
 * Right-rail Resources card (Rate calculator, Track a shipment, and Help Center / Support).
 * Uses `tenant.settings.support.help_center_url` when configured in Settings (D5),
 * falling back to the tenant's public Contact & Support page (`/contact`).
 */
export function DashboardResourcesCard({ flow }: { flow: ServiceFlow }) {
  const { routeTo, tenant } = useTenant();
  const configuredHelpUrl = tenant?.settings?.support?.help_center_url?.trim();
  const helpHref = configuredHelpUrl || routeTo("/contact");
  const isExternalHelp = Boolean(configuredHelpUrl);

  return (
    <section aria-labelledby="dashboard-resources-heading" className="rounded-xl border bg-card p-4 shadow-sm">
      <h2 id="dashboard-resources-heading" className="mb-3 text-sm font-semibold text-foreground">
        Resources
      </h2>
      <div className="space-y-2">
        <ResourceLink href={routeTo(RATE_CALCULATOR_HREF[flow])} label="Rate calculator" icon={Calculator} />
        <ResourceLink href={routeTo(PUBLIC_TRACKING_HREF)} label="Track a shipment" icon={MapPin} isExternal />
        <ResourceLink
          href={helpHref}
          label={isExternalHelp ? "Help Center" : "Support & Contacts"}
          icon={BookOpen}
          isExternal
        />
      </div>
    </section>
  );
}
