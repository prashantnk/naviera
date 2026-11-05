// frontend/src/components/providers/wallet-provider.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getDashboardSummary: vi.fn(),
  listShipments: vi.fn(),
  listManifests: vi.fn(),
  listEligibleShipments: vi.fn(),
  getExceptionsSummary: vi.fn(),
  listExceptions: vi.fn(),
  listBillingInvoices: vi.fn(),
  listRemittances: vi.fn(),
  listWeightMismatchDisputes: vi.fn(),
  listSupportTickets: vi.fn(),
  listAppointments: vi.fn(),
  listSavedAddresses: vi.fn(),
}));

vi.mock("@/api_client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api_client")>()),
  AddressesService: { listSavedAddresses: api.listSavedAddresses },
  AppointmentsService: { listAppointments: api.listAppointments },
  DashboardService: { getDashboardSummary: api.getDashboardSummary },
  DisputesService: { listWeightMismatchDisputes: api.listWeightMismatchDisputes },
  ExceptionsService: {
    getExceptionsSummary: api.getExceptionsSummary,
    listExceptions: api.listExceptions,
  },
  InvoicesService: { listBillingInvoices: api.listBillingInvoices },
  ManifestsService: {
    listManifests: api.listManifests,
    listEligibleShipments: api.listEligibleShipments,
  },
  RemittancesService: { listRemittances: api.listRemittances },
  ShipmentsService: { listShipments: api.listShipments },
  SupportTicketsService: { listSupportTickets: api.listSupportTickets },
  WalletService: { getWalletOverview: vi.fn() },
}));

import { ExceptionCategory, ServiceFlow } from "@/api_client";
import { buildQueryCacheKey, enableQueryCacheForTests, getCachedQuery, setCachedQuery } from "@/lib/query-cache";
import { buildPrewarmJobs, runPrewarmJobs, type PrewarmCapabilities } from "./wallet-provider";

const CUSTOMER: PrewarmCapabilities = { isStaff: false, canBook: true, canViewFinanceDocuments: true };
const OPERATIONS: PrewarmCapabilities = { isStaff: true, canBook: false, canViewFinanceDocuments: false };

async function runAll(flow: ServiceFlow, caps: PrewarmCapabilities): Promise<void> {
  await runPrewarmJobs(buildPrewarmJobs("logismart-test", flow, caps), 2, () => false);
}

describe("WalletProvider pre-warmer", () => {
  beforeEach(() => {
    enableQueryCacheForTests(true);
    for (const fn of Object.values(api)) fn.mockReset().mockResolvedValue([]);
    api.listShipments.mockResolvedValue({ items: [], total: 0 });
    api.listSavedAddresses.mockResolvedValue([{ id: "wh-1" }]);
  });

  afterEach(() => {
    enableQueryCacheForTests(false);
  });

  it("warms only the active flow and skips B2B-only screens in B2C", async () => {
    await runAll(ServiceFlow.B2C, CUSTOMER);
    expect(api.getDashboardSummary).toHaveBeenCalledTimes(1);
    expect(api.getDashboardSummary).toHaveBeenCalledWith("B2C", 30, "logismart-test");
    expect(api.listShipments).toHaveBeenCalledWith(1, 50, false, undefined, undefined);
    expect(api.listManifests).toHaveBeenCalledTimes(1);
    expect(api.listEligibleShipments).toHaveBeenCalledWith("B2C", "wh-1", "logismart-test");
    expect(api.listAppointments).not.toHaveBeenCalled();
    expect(api.listExceptions).toHaveBeenCalledWith(
      ServiceFlow.B2C,
      ExceptionCategory.SHIPMENT_EXCEPTIONS,
      false,
      null,
      1,
      20,
      "logismart-test",
    );
    expect(
      getCachedQuery(
        buildQueryCacheKey("logismart-test", "session", "exceptions-workspace", {
          serviceFlow: ServiceFlow.B2C,
          category: ExceptionCategory.SHIPMENT_EXCEPTIONS,
          actionable: false,
          search: "",
          page: 1,
        }),
      ),
    ).toEqual({ summary: [], list: [] });
    expect(
      getCachedQuery(
        buildQueryCacheKey("logismart-test", "customer", "invoices", { tab: "INVOICE", search: "" }),
      ),
    ).toEqual([]);
  });

  it("warms B2B appointments only in the B2B flow", async () => {
    await runAll(ServiceFlow.B2B, CUSTOMER);
    expect(api.listAppointments).toHaveBeenCalledTimes(1);
    expect(api.getDashboardSummary).toHaveBeenCalledWith("B2B", 30, "logismart-test");
    expect(api.listExceptions).toHaveBeenCalledWith(
      ServiceFlow.B2B,
      ExceptionCategory.PAYMENT_DISPUTE,
      false,
      null,
      1,
      20,
      "logismart-test",
    );
    expect(
      getCachedQuery(
        buildQueryCacheKey("logismart-test", "session", "exceptions-workspace", {
          serviceFlow: ServiceFlow.B2B,
          category: ExceptionCategory.PAYMENT_DISPUTE,
          actionable: false,
          search: "",
          page: 1,
        }),
      ),
    ).toEqual({ summary: [], list: [] });
  });

  it("skips screens the role cannot open (booking, finance documents)", async () => {
    await runAll(ServiceFlow.B2C, OPERATIONS);
    expect(api.listSavedAddresses).not.toHaveBeenCalled();
    expect(api.listEligibleShipments).not.toHaveBeenCalled();
    expect(api.listBillingInvoices).not.toHaveBeenCalled();
    expect(api.listRemittances).not.toHaveBeenCalled();
    expect(
      getCachedQuery(buildQueryCacheKey("logismart-test", "staff", "weight-mismatch", { search: "" })),
    ).toEqual([]);
  });

  it("does not refetch what the opened screen already cached", async () => {
    setCachedQuery(
      buildQueryCacheKey("logismart-test", "session", "dashboard-summary", { flow: "B2C", days: 30 }),
      { stages: {} },
    );
    await runAll(ServiceFlow.B2C, CUSTOMER);
    expect(api.getDashboardSummary).not.toHaveBeenCalled();
  });

  it("keeps at most `concurrency` requests in flight and stops when cancelled", async () => {
    let inFlight = 0;
    let peak = 0;
    let started = 0;
    let cancelled = false;
    const job = async () => {
      started += 1;
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight -= 1;
      if (started === 4) cancelled = true;
    };
    await runPrewarmJobs(Array.from({ length: 10 }, () => job), 2, () => cancelled);
    expect(peak).toBe(2);
    expect(started).toBeLessThan(10);
  });

  it("swallows a failing job and continues with the rest", async () => {
    const order: string[] = [];
    await runPrewarmJobs(
      [
        async () => {
          order.push("a");
          throw new Error("502");
        },
        async () => {
          order.push("b");
        },
      ],
      1,
      () => false,
    );
    expect(order).toEqual(["a", "b"]);
  });
});
