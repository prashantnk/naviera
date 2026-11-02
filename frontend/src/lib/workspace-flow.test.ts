// frontend/src/lib/workspace-flow.test.ts
import { describe, expect, it } from "vitest";

import {
  DEFAULT_SERVICE_FLOW,
  ServiceFlow,
  getFlowStorageKey,
  parseServiceFlow,
  resolveActiveFlow,
  resolveFlowFromPath,
  resolveLockedFlow,
  toTenantRelativePath,
} from "./workspace-flow";

const TENANT = "logismart";

describe("toTenantRelativePath", () => {
  it("strips the tenant segment in path-routing mode", () => {
    expect(toTenantRelativePath("/logismart/b2b/shipments", TENANT)).toBe("/b2b/shipments");
    expect(toTenantRelativePath("/logismart", TENANT)).toBe("/");
  });

  it("leaves subdomain-mode paths unchanged", () => {
    expect(toTenantRelativePath("/b2b/shipments", TENANT)).toBe("/b2b/shipments");
  });

  it("does not strip a look-alike prefix", () => {
    expect(toTenantRelativePath("/logismartx/dashboard", TENANT)).toBe("/logismartx/dashboard");
  });
});

describe("resolveFlowFromPath", () => {
  it("maps every /b2b route to B2B", () => {
    expect(resolveFlowFromPath("/logismart/b2b/dashboard", TENANT)).toBe(ServiceFlow.B2B);
    expect(resolveFlowFromPath("/logismart/b2b/shipments/abc", TENANT)).toBe(ServiceFlow.B2B);
    expect(resolveFlowFromPath("/b2b/pickup-requests", TENANT)).toBe(ServiceFlow.B2B);
    expect(resolveFlowFromPath("/logismart/b2b/appointments", TENANT)).toBe(ServiceFlow.B2B);
    expect(resolveFlowFromPath("/logismart/b2b/delivery-exceptions", TENANT)).toBe(ServiceFlow.B2B);
  });

  it("maps B2C-only routes to B2C", () => {
    expect(resolveFlowFromPath("/logismart/dashboard", TENANT)).toBe(ServiceFlow.B2C);
    expect(resolveFlowFromPath("/logismart/shipments/new/reverse", TENANT)).toBe(ServiceFlow.B2C);
    expect(resolveFlowFromPath("/logismart/rate-calculator", TENANT)).toBe(ServiceFlow.B2C);
    expect(resolveFlowFromPath("/logismart/delivery-exceptions", TENANT)).toBe(ServiceFlow.B2C);
    expect(resolveFlowFromPath("/logismart/pickup-requests", TENANT)).toBe(ServiceFlow.B2C);
    expect(resolveFlowFromPath("/logismart/pickup-requests/new", TENANT)).toBe(ServiceFlow.B2C);
    expect(resolveFlowFromPath("/logismart/b2b/pickup-requests/new", TENANT)).toBe(ServiceFlow.B2B);
  });

  it("returns null for shared pages and unknown input", () => {
    expect(resolveFlowFromPath("/logismart/wallet", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/address-book", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/settings", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/team", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/finances/remittances", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/finances/invoices/abc", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/disputes/weight-mismatch", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/support", TENANT)).toBeNull();
    expect(resolveFlowFromPath("/logismart/ops", TENANT)).toBeNull();
    expect(resolveFlowFromPath(null, TENANT)).toBeNull();
  });

  it("does not treat look-alike routes as B2B", () => {
    expect(resolveFlowFromPath("/logismart/b2bx", TENANT)).toBeNull();
  });
});

describe("resolveLockedFlow", () => {
  it("locks single-service users to their flow", () => {
    expect(resolveLockedFlow(true, false)).toBe(ServiceFlow.B2C);
    expect(resolveLockedFlow(false, true)).toBe(ServiceFlow.B2B);
  });

  it("does not lock users who can access both", () => {
    expect(resolveLockedFlow(true, true)).toBeNull();
  });
});

describe("resolveActiveFlow precedence", () => {
  it("scope lock beats URL and saved choice", () => {
    expect(resolveActiveFlow(ServiceFlow.B2C, ServiceFlow.B2B, ServiceFlow.B2B)).toBe(ServiceFlow.B2C);
  });

  it("URL beats saved choice", () => {
    expect(resolveActiveFlow(null, ServiceFlow.B2B, ServiceFlow.B2C)).toBe(ServiceFlow.B2B);
  });

  it("saved choice applies on shared pages", () => {
    expect(resolveActiveFlow(null, null, ServiceFlow.B2B)).toBe(ServiceFlow.B2B);
  });

  it("falls back to the default flow", () => {
    expect(resolveActiveFlow(null, null, null)).toBe(DEFAULT_SERVICE_FLOW);
    expect(DEFAULT_SERVICE_FLOW).toBe(ServiceFlow.B2C);
  });
});

describe("storage helpers", () => {
  it("parses only valid flows", () => {
    expect(parseServiceFlow("B2B")).toBe(ServiceFlow.B2B);
    expect(parseServiceFlow("B2C")).toBe(ServiceFlow.B2C);
    expect(parseServiceFlow("ALL")).toBeNull();
    expect(parseServiceFlow(null)).toBeNull();
  });

  it("scopes the storage key per tenant", () => {
    expect(getFlowStorageKey("logismart")).toBe("naviera-flow-logismart");
    expect(getFlowStorageKey("naviera")).not.toBe(getFlowStorageKey("logismart"));
  });
});
