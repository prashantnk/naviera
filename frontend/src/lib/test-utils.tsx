import React, { ReactElement } from "react";
import { render, RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TenantProvider } from "@/components/providers/tenant-provider";
import { Tenant } from "@/types/tenant";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

const mockTenant: Tenant = {
  id: "test-tenant-id",
  slug: "naviera",
  name: "Test Tenant",
  settings: {
    brand: {
      primary_color: "#FF6B35",
      secondary_color: "#00707F",
    }
  },
};

const AllTheProviders = ({ children }: { children: React.ReactNode }) => {
  return (
    <QueryClientProvider client={queryClient}>
      <TenantProvider tenant={mockTenant} routingMode="subdomain">
        {children}
      </TenantProvider>
    </QueryClientProvider>
  );
};

const customRender = (
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">
) => render(ui, { wrapper: AllTheProviders, ...options });

export * from "@testing-library/react";
export { customRender as render };
