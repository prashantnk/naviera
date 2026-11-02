// frontend/src/app/[tenant_slug]/(app)/support/support-and-team.test.tsx
import { UserRole } from "@/api_client";
import { CLAIMS_FINANCE_CHIP } from "@/components/support/ticket-rules";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { USER_ROLES } from "../team/page";
import SupportTicketsPage, {
  CLOSED_TICKET_CUSTOMER_NOTICE,
  isSupportStaffSender,
} from "./page";

const mockListSupportTickets = vi.fn();
const mockGetSupportTicket = vi.fn();
const mockCreateSupportTicket = vi.fn();

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    SupportTicketsService: {
      listSupportTickets: (...args: unknown[]) => mockListSupportTickets(...args),
      getSupportTicket: (...args: unknown[]) => mockGetSupportTicket(...args),
      createSupportTicket: (...args: unknown[]) => mockCreateSupportTicket(...args),
      addSupportTicketMessage: vi.fn(),
      updateSupportTicketStatus: vi.fn(),
    },
  };
});

const mockUseUser = vi.fn();

vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => mockUseUser(),
}));

/** `useUser()` of a customer (or, with overrides, another role). */
function _userContext(capabilities: Record<string, boolean> = {}) {
  return {
    isAdmin: false,
    user: { id: "u-cust", email: "seller@example.com", role: UserRole.CUSTOMER },
    capabilities: {
      isStaff: false,
      canWrite: true,
      canHandleSupport: false,
      ...capabilities,
    },
  };
}

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ tenant: null, tenantSlug: "logismart-test", routeTo: (p: string) => p }),
}));

describe("Support tickets D-19 & IST timestamps (F-02)", () => {
  beforeEach(() => {
    mockListSupportTickets.mockReset();
    mockGetSupportTicket.mockReset();
    mockCreateSupportTicket.mockReset();
    mockUseUser.mockReturnValue(_userContext());
    window.history.replaceState(null, "", "/support");
  });

  it("classifies tenant staff vs customer sender roles accurately", () => {
    expect(isSupportStaffSender("owner")).toBe(true);
    expect(isSupportStaffSender("admin")).toBe(true);
    expect(isSupportStaffSender("support_user")).toBe(true);
    expect(isSupportStaffSender("operations_user")).toBe(true);
    expect(isSupportStaffSender("customer")).toBe(false);
    expect(isSupportStaffSender("")).toBe(false);
    expect(isSupportStaffSender(null)).toBe(false);
  });

  it("hides dead Email notifications & CC controls in Raise Ticket modal", async () => {
    mockListSupportTickets.mockResolvedValue([]);
    render(<SupportTicketsPage />);

    const raiseButtons = await screen.findAllByRole("button", {
      name: /Raise a ticket/i,
    });
    fireEvent.click(raiseButtons[0]);

    expect(screen.queryByText(/Email notifications/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Add more CC emails/i)).not.toBeInTheDocument();
  });

  it("labels support_user as Support Agent and blocks customer replies on CLOSED tickets", async () => {
    mockListSupportTickets.mockResolvedValue([
      {
        id: "tkt-1",
        ticket_number: "TKT-20261030-0001",
        category_group: "SHIPMENT_ISSUE",
        sub_category: "Firstmile / Seller Pickup related issues",
        subject: "Pickup delayed",
        description: "Need pickup",
        status: "CLOSED",
        created_at: "2026-10-29T20:00:00",
        updated_at: "2026-10-29T20:30:00",
      },
    ]);
    mockGetSupportTicket.mockResolvedValue({
      id: "tkt-1",
      ticket_number: "TKT-20261030-0001",
      category_group: "SHIPMENT_ISSUE",
      sub_category: "Firstmile / Seller Pickup related issues",
      subject: "Pickup delayed",
      description: "Need pickup",
      status: "CLOSED",
      raised_by_email: "seller@example.com",
      created_at: "2026-10-29T20:00:00",
      updated_at: "2026-10-29T20:30:00",
      messages: [
        {
          id: "m-1",
          ticket_id: "tkt-1",
          sender_user_id: "u-cust",
          sender_email: "seller@example.com",
          sender_role: "customer",
          message: "Need pickup today",
          created_at: "2026-10-29T20:00:00",
        },
        {
          id: "m-2",
          ticket_id: "tkt-1",
          sender_user_id: "u-sup",
          sender_email: "support@logismart.in",
          sender_role: "support_user",
          message: "Resolved and closed",
          created_at: "2026-10-29T20:30:00",
        },
      ],
    });

    render(<SupportTicketsPage />);
    const [row] = await screen.findAllByText("TKT-20261030-0001");
    fireEvent.click(row);

    await waitFor(() => expect(mockGetSupportTicket).toHaveBeenCalledWith("tkt-1"));
    expect(await screen.findByText("Support Agent")).toBeInTheDocument();
    expect(screen.getAllByText("Merchant").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("CC Recipients")).not.toBeInTheDocument();

    const closedNotice = screen.getByTestId("closed-ticket-customer-notice");
    expect(closedNotice).toHaveTextContent(CLOSED_TICKET_CUSTOMER_NOTICE);
    expect(closedNotice).toHaveTextContent(/reopen by raising a new ticket/i);
    expect(
      screen.queryByPlaceholderText(/Write a reply/i)
    ).not.toBeInTheDocument();
  });

  it("requires the AWB for a shipment issue but not for Claims / Finance", async () => {
    mockListSupportTickets.mockResolvedValue([]);
    render(<SupportTicketsPage />);
    fireEvent.click(await screen.findByTestId("support.actions.raise"));

    fireEvent.click(screen.getByRole("button", { name: "Damage / Missing / Mismatch" }));
    fireEvent.change(screen.getByLabelText(/Describe your issue/i), {
      target: { value: "Box arrived crushed" },
    });
    const submit = screen.getByRole("button", { name: "Submit Ticket" });
    expect(submit).toBeDisabled();
    expect(screen.getByTestId("support.raise.awb")).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(screen.getByTestId("support.raise.awb"), {
      target: { value: "LOGISMART-TEST-AAAA1111" },
    });
    expect(submit).toBeEnabled();

    fireEvent.change(screen.getByTestId("support.raise.awb"), { target: { value: "" } });
    fireEvent.click(
      screen.getByRole("button", { name: CLAIMS_FINANCE_CHIP })
    );
    expect(screen.getByRole("button", { name: "Submit Ticket" })).toBeEnabled();
    expect(screen.getByText("(optional)")).toBeInTheDocument();
  });

  it("opens a pre-filled ticket from the weight-claim Need help? deep link", async () => {
    mockListSupportTickets.mockResolvedValue([]);
    mockCreateSupportTicket.mockResolvedValue({ ticket_number: "TKT-20261101-0009" });
    window.history.replaceState(
      null,
      "",
      `/support?awb=LOGISMART-TEST-ZZZZ9999&category=${encodeURIComponent(CLAIMS_FINANCE_CHIP)}`
    );
    render(<SupportTicketsPage />);

    expect(await screen.findByTestId("support.raise.awb")).toHaveValue("LOGISMART-TEST-ZZZZ9999");
    expect(screen.getByLabelText("Subject")).toHaveValue(CLAIMS_FINANCE_CHIP);
    fireEvent.change(screen.getByLabelText(/Describe your issue/i), {
      target: { value: "My weight claim was rejected but the box is 1 kg" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit Ticket" }));

    await waitFor(() => expect(mockCreateSupportTicket).toHaveBeenCalledTimes(1));
    expect(mockCreateSupportTicket.mock.calls[0][0]).toMatchObject({
      category_group: "SHIPMENT_ISSUE",
      sub_category: CLAIMS_FINANCE_CHIP,
      tracking_id: "LOGISMART-TEST-ZZZZ9999",
    });
  });

  it("hides raise and reply for a read-only user", async () => {
    mockUseUser.mockReturnValue(
      _userContext({ isStaff: true, canWrite: false, canHandleSupport: false })
    );
    mockListSupportTickets.mockResolvedValue([
      {
        id: "tkt-2",
        ticket_number: "TKT-20261030-0002",
        category_group: "SHIPMENT_ISSUE",
        sub_category: "Delivery Query",
        description: "Where is it",
        status: "OPEN",
        created_at: "2026-10-29T20:00:00",
        updated_at: "2026-10-29T20:30:00",
      },
    ]);
    mockGetSupportTicket.mockResolvedValue({
      id: "tkt-2",
      ticket_number: "TKT-20261030-0002",
      category_group: "SHIPMENT_ISSUE",
      sub_category: "Delivery Query",
      status: "OPEN",
      created_at: "2026-10-29T20:00:00",
      updated_at: "2026-10-29T20:30:00",
      messages: [],
    });
    render(<SupportTicketsPage />);

    const [row] = await screen.findAllByText("TKT-20261030-0002");
    expect(screen.queryByTestId("support.actions.raise")).not.toBeInTheDocument();
    fireEvent.click(row);
    expect(await screen.findByTestId("read-only-ticket-notice")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Write a reply/i)).not.toBeInTheDocument();
  });
});

describe("Team role checklist copy (B-07)", () => {
  it("matches actual RBAC capabilities for operations, support, admin, and read-only", () => {
    const byKey = new Map(USER_ROLES.map((r) => [r.key, r.capabilities.join(" | ")]));

    expect(byKey.get(UserRole.OPERATIONS_USER)).toMatch(
      /No access to tenant wallet, COD remittances, GST invoices/i
    );
    expect(byKey.get(UserRole.SUPPORT_USER)).toMatch(
      /No access to tenant wallet, COD remittances, GST invoices/i
    );
    expect(byKey.get(UserRole.ADMIN)).toMatch(
      /Owner required to promote\/modify Admins/i
    );
    expect(byKey.get(UserRole.READ_ONLY_USER)).toMatch(
      /Strict write block on all mutations/i
    );
  });
});
