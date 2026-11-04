// frontend/src/components/profile/company-details-section.test.tsx
import type { UserRead } from "@/api_client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  companyDetailsSchema,
  toCompanyDetailsPayload,
} from "./company-details-form";
import { CompanyDetailsSection } from "./company-details-section";

const updateMyProfile = vi.fn();
const userState: { user: Partial<UserRead> | null; isAdmin: boolean } = {
  user: null,
  isAdmin: false,
};

vi.mock("@/api_client", () => ({
  UsersService: { updateMyProfile: (...args: unknown[]) => updateMyProfile(...args) },
}));
vi.mock("@/components/auth/auth-guard", () => ({ useUser: () => userState }));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}` }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SELLER: Partial<UserRead> = {
  id: "u-1",
  email: "seller@example.com",
  company_details_locked: false,
};

describe("companyDetailsSchema", () => {
  it("accepts a blank GSTIN as unregistered and upper-cases a typed one", () => {
    const blank = companyDetailsSchema.parse({
      legalName: " Acme Traders ",
      billingAddress: "12 MG Road, Bengaluru 560001",
      gstin: "",
    });
    expect(toCompanyDetailsPayload(blank)).toEqual({
      legal_name: "Acme Traders",
      billing_address: "12 MG Road, Bengaluru 560001",
      gstin: null,
    });
    const typed = companyDetailsSchema.parse({
      legalName: "Acme Traders",
      billingAddress: "12 MG Road, Bengaluru 560001",
      gstin: "29aagcb7383j1z4",
    });
    expect(typed.gstin).toBe("29AAGCB7383J1Z4");
  });

  it.each(["29AAGCB7383J1Z", "ABCDE", "2AAAGCB7383J1Z4"])("rejects a malformed GSTIN %s", (gstin) => {
    const result = companyDetailsSchema.safeParse({
      legalName: "Acme Traders",
      billingAddress: "12 MG Road, Bengaluru 560001",
      gstin,
    });
    expect(result.success).toBe(false);
  });

  it("requires a name and a full billing address", () => {
    const result = companyDetailsSchema.safeParse({ legalName: "A", billingAddress: "short", gstin: "" });
    expect(result.success).toBe(false);
  });
});

describe("CompanyDetailsSection", () => {
  beforeEach(() => {
    updateMyProfile.mockReset();
    userState.user = { ...SELLER };
    userState.isAdmin = false;
  });

  it("is hidden for staff accounts", () => {
    userState.isAdmin = true;
    const { container } = render(<CompanyDetailsSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it("submits the company details once through PATCH /users/me", async () => {
    updateMyProfile.mockResolvedValue({});
    render(<CompanyDetailsSection />);

    fireEvent.change(screen.getByTestId("profile.company-details.legal-name"), {
      target: { value: "Acme Traders" },
    });
    fireEvent.change(screen.getByTestId("profile.company-details.billing-address"), {
      target: { value: "12 MG Road, Bengaluru 560001" },
    });
    fireEvent.change(screen.getByTestId("profile.company-details.gstin-input"), {
      target: { value: "29AAGCB7383J1Z4" },
    });
    fireEvent.click(screen.getByTestId("profile.company-details.save"));

    await waitFor(() => expect(updateMyProfile).toHaveBeenCalledTimes(1));
    expect(updateMyProfile).toHaveBeenCalledWith({
      company_details: {
        legal_name: "Acme Traders",
        billing_address: "12 MG Road, Bengaluru 560001",
        gstin: "29AAGCB7383J1Z4",
      },
    });
    // BUG-09: immediately switches to locked view without requiring a page reload
    await waitFor(() =>
      expect(screen.getByTestId("profile.company-details.view")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("profile.company-details.form")).not.toBeInTheDocument();
    expect(screen.getByTestId("profile.company-details.gstin")).toHaveTextContent("29AAGCB7383J1Z4");
  });

  it("shows locked details read-only with a support-ticket link", () => {
    userState.user = {
      ...SELLER,
      company_details_locked: true,
      company_name: "Acme Traders",
      billing_address: "12 MG Road, Bengaluru 560001",
      gstin: null,
    };
    render(<CompanyDetailsSection />);

    expect(screen.getByTestId("profile.company-details.view")).toBeInTheDocument();
    expect(screen.getByTestId("profile.company-details.gstin")).toHaveTextContent("Unregistered");
    expect(screen.queryByTestId("profile.company-details.form")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "raise a support ticket" })).toHaveAttribute(
      "href",
      "/t/support"
    );
  });
});
