// frontend/src/components/providers/tenant-provider.tsx
"use client";

import { configureApiClient } from "@/lib/api-config";
import { Tenant } from "@/types/tenant";
import { useParams } from "next/navigation";
import React, { createContext, useContext, useCallback } from "react";

interface TenantContextType {
  tenant: Tenant | null;
  tenantSlug: string;
  routingMode: "subdomain" | "path";
  routeTo: (path: string) => string;
}

const TenantContext = createContext<TenantContextType | undefined>(undefined);

export function TenantProvider({
  children,
  tenant,
  routingMode,
}: {
  children: React.ReactNode;
  tenant: Tenant | null;
  routingMode: "subdomain" | "path";
}) {
  const params = useParams();
  const tenantSlug = (params?.tenant_slug as string) || "naviera";

  configureApiClient(tenantSlug);

  // 🔥 FIX: Wrapped in useCallback to prevent infinite render loops in child components!
  const routeTo = useCallback(
    (path: string) => {
      const cleanPath = path.startsWith("/") ? path : `/${path}`;

      if (routingMode === "subdomain") {
        return cleanPath;
      } else {
        if (cleanPath.startsWith(`/${tenantSlug}`)) return cleanPath;
        return `/${tenantSlug}${cleanPath}`;
      }
    },
    [routingMode, tenantSlug]
  );

  return (
    <TenantContext.Provider
      value={{ tenant, tenantSlug, routingMode, routeTo }}
    >
      {children}
    </TenantContext.Provider>
  );
}

export function useTenant() {
  const context = useContext(TenantContext);
  if (context === undefined) {
    throw new Error("useTenant must be used within a TenantProvider");
  }
  return context;
}
