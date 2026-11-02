// frontend/src/lib/legal.test.tsx
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Tenant } from "@/types/tenant";
import {
  DRAFT_LIABILITY_CAP_INR,
  GRIEVANCE_FIELD_FALLBACK,
  LEGAL_DRAFT_BANNER_TEXT,
  LEGAL_PATHS,
  PROHIBITED_ITEMS,
  legalEntityName,
  resolveGrievanceOfficer,
} from "./legal";

const getTenantBySlug = vi.fn<(slug: string) => Promise<Tenant | null>>();

vi.mock("@/lib/api", () => ({
  getTenantBySlug: (slug: string) => getTenantBySlug(slug),
}));

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/logismart-test${path}` }),
}));

const TENANT: Tenant = {
  id: "t1",
  name: "Logismart Test",
  slug: "logismart-test",
  settings: {
    contact: {
      emails: ["support@logismart.in"],
      grievance_officer: { name: "  A. Sharma ", email: "grievance@logismart.in", phone: "" },
    },
  },
};

const params = Promise.resolve({ tenant_slug: "logismart-test" });

describe("resolveGrievanceOfficer", () => {
  it("uses configured fields and falls back per blank field", () => {
    expect(resolveGrievanceOfficer(TENANT.settings)).toEqual({
      name: "A. Sharma",
      email: "grievance@logismart.in",
      phone: GRIEVANCE_FIELD_FALLBACK,
      isConfigured: true,
    });
  });

  it("is 'To be announced' everywhere when nothing is configured", () => {
    expect(resolveGrievanceOfficer(undefined)).toEqual({
      name: GRIEVANCE_FIELD_FALLBACK,
      email: GRIEVANCE_FIELD_FALLBACK,
      phone: GRIEVANCE_FIELD_FALLBACK,
      isConfigured: false,
    });
  });

  it("legalEntityName falls back to the platform name", () => {
    expect(legalEntityName(" Logismart ")).toBe("Logismart");
    expect(legalEntityName("")).toBe("Naviera");
  });
});

describe("public legal pages (C-08)", () => {
  beforeEach(() => {
    getTenantBySlug.mockResolvedValue(TENANT);
  });

  async function renderPage(load: () => Promise<{ default: (p: { params: typeof params }) => Promise<ReactElement> }>) {
    const { default: Page } = await load();
    render(await Page({ params }));
  }

  it.each([
    ["terms", () => import("@/app/[tenant_slug]/(marketing)/terms/page"), "Terms of Service & Carriage"],
    ["privacy", () => import("@/app/[tenant_slug]/(marketing)/privacy/page"), "Privacy Policy"],
    ["refund", () => import("@/app/[tenant_slug]/(marketing)/refund-policy/page"), "Refund & Cancellation Policy"],
    ["prohibited", () => import("@/app/[tenant_slug]/(marketing)/prohibited-items/page"), "Prohibited & Restricted Items"],
    ["grievance", () => import("@/app/[tenant_slug]/(marketing)/grievance/page"), "Grievance Officer"],
  ])("%s page shows the title, tenant name and the draft banner", async (_name, load, title) => {
    await renderPage(load);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.getByTestId("legal.draft-banner")).toHaveTextContent(LEGAL_DRAFT_BANNER_TEXT);
    expect(screen.getAllByText(/Logismart Test/).length).toBeGreaterThan(0);
  });

  it("terms cover carriage rules and link to the other policies via routeTo", async () => {
    await renderPage(() => import("@/app/[tenant_slug]/(marketing)/terms/page"));
    for (const heading of [/Prohibited and restricted items/, /volumetric weight/i, /Cash on Delivery/, /Our liability/, /Claims for loss/]) {
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link", { name: "Privacy Policy" })[0]).toHaveAttribute(
      "href",
      `/logismart-test${LEGAL_PATHS.privacy}`,
    );
    expect(screen.getByRole("link", { name: "Prohibited & Restricted Items" })).toHaveAttribute(
      "href",
      `/logismart-test${LEGAL_PATHS.prohibited}`,
    );
    expect(DRAFT_LIABILITY_CAP_INR).toBe("₹5,000");
    expect(screen.getByText(/₹5,000 per shipment \(draft figure, to be confirmed\)/)).toBeInTheDocument();
  });

  it("prohibited-items page lists every prohibited item and links back to the terms", async () => {
    await renderPage(() => import("@/app/[tenant_slug]/(marketing)/prohibited-items/page"));
    for (const item of PROHIBITED_ITEMS) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Terms of Service & Carriage" })).toHaveAttribute(
      "href",
      `/logismart-test${LEGAL_PATHS.terms}`,
    );
  });

  it("grievance page shows the configured officer with per-field fallback", async () => {
    await renderPage(() => import("@/app/[tenant_slug]/(marketing)/grievance/page"));
    const officer = screen.getByTestId("grievance.officer");
    expect(officer).toHaveTextContent("A. Sharma");
    expect(officer).toHaveTextContent("grievance@logismart.in");
    expect(officer).toHaveTextContent(GRIEVANCE_FIELD_FALLBACK);
    expect(screen.queryByTestId("grievance.support-fallback")).not.toBeInTheDocument();
  });

  it("grievance page says 'To be announced' and points to support when unset", async () => {
    getTenantBySlug.mockResolvedValue({ ...TENANT, settings: { contact: { emails: ["support@logismart.in"] } } });
    await renderPage(() => import("@/app/[tenant_slug]/(marketing)/grievance/page"));
    expect(screen.getByTestId("grievance.officer")).toHaveTextContent(GRIEVANCE_FIELD_FALLBACK);
    expect(screen.getByTestId("grievance.support-fallback")).toHaveTextContent("support@logismart.in");
  });
});
