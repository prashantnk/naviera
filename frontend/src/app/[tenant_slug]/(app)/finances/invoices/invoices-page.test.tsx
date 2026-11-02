// frontend/src/app/[tenant_slug]/(app)/finances/invoices/invoices-page.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InvoicesListPage from "./page";

const mockList = vi.fn();
const mockUseUser = vi.fn();

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    InvoicesService: { listBillingInvoices: (...a: unknown[]) => mockList(...a) },
  };
});
vi.mock("@/components/auth/auth-guard", () => ({ useUser: () => mockUseUser() }));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ tenant: null, tenantSlug: "logismart-test", routeTo: (p: string) => p }),
}));

function doc(invoice_number: string, note_type: string, invoice_date: string) {
  return {
    id: invoice_number,
    tenant_id: "t",
    merchant_user_id: "m",
    invoice_number,
    note_type,
    service_type: "Domestic",
    invoice_date,
    due_date: invoice_date,
    status: "Paid",
    gst_number: "06AAECL2138H1ZQ",
    billing_address: "Gurgaon",
    total_amount: 159.3,
    created_at: invoice_date,
    document_title: note_type === "INVOICE" ? "Tax Invoice" : "Credit Note",
    is_note: note_type !== "INVOICE",
    tax_rows: [],
    place_of_supply_label: null,
    bill_to: null,
    supplier_name: null,
    original_invoice_number: null,
    original_invoice_date: null,
    tracking_id: `AWB-${invoice_number}`,
    merchant_email: "seller@example.com",
  };
}

describe("Invoices list", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockUseUser.mockReturnValue({ capabilities: { isStaff: false } });
  });

  it("has no fake date chip, shows the AWB, and filters by a real date range", async () => {
    mockList.mockResolvedValue([
      doc("INV-OCT", "INVOICE", "2026-10-31T10:00:00"),
      doc("INV-SEP", "INVOICE", "2026-09-15T10:00:00"),
    ]);
    render(<InvoicesListPage />);

    expect((await screen.findAllByText("INV-OCT")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/16 Sept 2026 to 16 Oct 2026/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/AWB-INV-OCT/).length).toBeGreaterThan(0);
    expect(screen.queryByText("seller@example.com")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("invoices.filters.from"), { target: { value: "2026-10-01" } });
    expect(screen.queryAllByText("INV-SEP")).toHaveLength(0);
    expect(screen.getAllByText("INV-OCT").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByTestId("invoices.filters.to"), { target: { value: "2026-10-30" } });
    expect(screen.getByText("No documents found in this tab")).toBeInTheDocument();
  });

  it("labels document types and note columns on the All / Credit Notes tabs", async () => {
    mockUseUser.mockReturnValue({ capabilities: { isStaff: true } });
    mockList.mockResolvedValue([
      doc("INV-1", "INVOICE", "2026-10-31T10:00:00"),
      doc("CN-1", "CREDIT_NOTE", "2026-10-31T11:00:00"),
    ]);
    render(<InvoicesListPage />);
    await screen.findAllByText("INV-1");

    fireEvent.click(screen.getByTestId("invoices.tabs.all"));
    expect(await screen.findByText("DOCUMENT ID")).toBeInTheDocument();
    expect(screen.getAllByText("Credit note").length).toBeGreaterThan(0);
    expect(screen.getByTestId("invoices.row.INV-1.merchant")).toHaveTextContent("seller@example.com");

    fireEvent.click(screen.getByTestId("invoices.tabs.credit-notes"));
    expect(await screen.findByText("NOTE ID")).toBeInTheDocument();
    expect(mockList).toHaveBeenLastCalledWith("CREDIT_NOTE", null, "logismart-test");
  });
});
