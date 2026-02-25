// src/components/providers/tenant-provider.tsx
"use client";

import { Tenant } from "@/types/tenant";
import { useParams } from "next/navigation";
import React, { createContext, useContext } from "react";

interface TenantContextType {
    tenant: Tenant | null;
    tenantSlug: string;
    routingMode: "subdomain" | "path";
    routeTo: (path: string) => string; // <-- The Magic Function
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

    // The Magic URL Resolver
    const routeTo = (path: string) => {
        const cleanPath = path.startsWith("/") ? path : `/${path}`;

        if (routingMode === "subdomain") {
            // In subdomain mode, keep links clean (e.g., "/login")
            return cleanPath;
        } else {
            // In path mode, force the prefix to avoid breaking out (e.g., "/logismart/login")
            if (cleanPath.startsWith(`/${tenantSlug}`)) return cleanPath;
            return `/${tenantSlug}${cleanPath}`;
        }
    };

    return (
        <TenantContext.Provider value={{ tenant, tenantSlug, routingMode, routeTo }}>
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