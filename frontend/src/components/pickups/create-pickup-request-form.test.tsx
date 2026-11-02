// frontend/src/components/pickups/create-pickup-request-form.test.tsx
import { ServiceFlow } from "@/api_client";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CreatePickupRequestForm } from "./create-pickup-request-form";

const mockCreate = vi.fn();
const ADDRESS = {
  id: "addr-1",
  name: "LogiSmart B2C Gurugram Hub Warehouse",
  pincode: "122001",
  city: "Gurugram",
  state: "Haryana",
};

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    AddressesService: { listSavedAddresses: () => Promise.resolve([ADDRESS]) },
    ManifestsService: {
      // The Ready to Ship list never arrives (slow network).
      listEligibleShipments: () => new Promise(() => {}),
      createManifest: (...args: unknown[]) => mockCreate(...args),
    },
  };
});
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}`, tenantSlug: "t" }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

describe("CreatePickupRequestForm (journey-2: no empty PUR while the list loads)", () => {
  it("keeps 'Create Pickup Request' disabled until the Ready to Ship list has loaded", async () => {
    render(
      <CreatePickupRequestForm
        serviceFlow={ServiceFlow.B2C}
        initialLocationId="addr-1"
        initialLocationName={ADDRESS.name}
        initialShipmentIds={["ship-1"]}
      />,
    );
    const submit = await screen.findByRole("button", { name: /Create Pickup Request/ });
    await waitFor(() => expect(submit).toBeDisabled());
    expect(mockCreate).not.toHaveBeenCalled();
  });
});
