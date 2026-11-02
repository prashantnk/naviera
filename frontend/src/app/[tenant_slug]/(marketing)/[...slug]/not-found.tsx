// frontend/src/app/[tenant_slug]/(marketing)/[...slug]/not-found.tsx
import { TenantLink } from "@/components/blocks/tenant-link";
import { Button } from "@/components/ui/button";
import { FileQuestion, Home } from "lucide-react";

/**
 * Tenant-branded "Page Not Found" for unknown public paths (rendered by the
 * catch-all's `notFound()`, served with HTTP 404). The home link goes through
 * `routeTo()` so it also works when the tenant is served from its own subdomain.
 */
export default function MarketingNotFound() {
  return (
    <div className="py-24 flex flex-col items-center justify-center text-center px-4 bg-muted/30">
      <div className="max-w-md space-y-8">
        <div className="mx-auto w-24 h-24 bg-primary/10 rounded-full flex items-center justify-center mb-2">
          <FileQuestion className="h-12 w-12 text-primary" />
        </div>

        <div className="space-y-3">
          <h1 className="text-4xl md:text-5xl font-extrabold text-foreground tracking-tight">
            Page Not Found
          </h1>
          <p className="text-lg text-muted-foreground">
            We couldn&apos;t find the page you asked for. It might have been
            moved, deleted, or never existed in the first place.
          </p>
        </div>

        <div className="pt-4">
          <Button
            asChild
            size="lg"
            className="rounded-xl h-14 px-8 text-base font-bold shadow-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
          >
            <TenantLink href="/" data-testid="not-found.home-link">
              <Home className="mr-2 h-5 w-5" /> Return to Homepage
            </TenantLink>
          </Button>
        </div>
      </div>
    </div>
  );
}
