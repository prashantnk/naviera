// frontend/src/components/blocks/tenant-link.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import Link from "next/link";
import type { ComponentProps } from "react";

/**
 * `next/link` that resolves a tenant-relative path through `routeTo()`, so
 * Server Components (e.g. the legal pages) can link to `/privacy` without
 * knowing whether the tenant is served by subdomain or by `/<slug>/` path.
 */
export function TenantLink({
  href,
  prefetch = true,
  ...rest
}: Omit<ComponentProps<typeof Link>, "href"> & { href: string }) {
  const { routeTo } = useTenant();
  return <Link href={routeTo(href)} prefetch={prefetch} {...rest} />;
}
