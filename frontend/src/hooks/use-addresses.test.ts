// frontend/src/hooks/use-addresses.test.ts
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AddressesService, type AddressRead } from "@/api_client";
import { enableQueryCacheForTests } from "@/lib/query-cache";
import {
  fetchAddressesCached,
  getCachedAddresses,
  hasCachedAddresses,
  invalidateAddressesCache,
  setCachedAddresses,
  useAddresses,
} from "./use-addresses";

vi.mock("@/api_client", () => ({
  AddressesService: {
    listSavedAddresses: vi.fn(),
  },
}));

const MOCK_ADDRESS: AddressRead = {
  id: "addr-1",
  name: "Mumbai Hub",
  phone: "9876543210",
  address_line1: "Plot 12, MIDC Andheri",
  city: "Mumbai",
  state: "Maharashtra",
  pincode: "400093",
  country: "India",
};

describe("useAddresses & cached address book helpers", () => {
  beforeEach(() => {
    enableQueryCacheForTests(true);
    vi.clearAllMocks();
  });

  afterEach(() => {
    enableQueryCacheForTests(false);
  });

  it("renders synchronously with loading=false when addresses are warm in query-cache", async () => {
    setCachedAddresses("logismart-test", [MOCK_ADDRESS]);
    vi.mocked(AddressesService.listSavedAddresses).mockResolvedValue([
      MOCK_ADDRESS,
    ]);

    expect(hasCachedAddresses("logismart-test")).toBe(true);
    expect(getCachedAddresses("logismart-test")).toEqual([MOCK_ADDRESS]);

    const { result } = renderHook(() => useAddresses("logismart-test"));
    expect(result.current.loading).toBe(false);
    expect(result.current.addresses).toEqual([MOCK_ADDRESS]);

    await waitFor(() => {
      expect(AddressesService.listSavedAddresses).toHaveBeenCalledTimes(1);
    });
  });

  it("fetches and caches addresses via fetchAddressesCached and invalidates on invalidateAddressesCache", async () => {
    vi.mocked(AddressesService.listSavedAddresses).mockResolvedValue([
      MOCK_ADDRESS,
    ]);

    const rows = await fetchAddressesCached("logismart-test");
    expect(rows).toEqual([MOCK_ADDRESS]);
    expect(hasCachedAddresses("logismart-test")).toBe(true);

    invalidateAddressesCache("logismart-test");
    expect(hasCachedAddresses("logismart-test")).toBe(false);
  });
});
