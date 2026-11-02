// frontend/src/components/profile/change-password-section.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { normalizeMobile } from "../blocks/profile-dialog";
import { ChangePasswordSection, newPasswordError } from "./change-password-section";

const mockUpdateUser = vi.fn();
const mockToastSuccess = vi.fn();

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({ auth: { updateUser: (...a: unknown[]) => mockUpdateUser(...a) } }),
}));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ tenantSlug: "logismart-test" }),
}));
vi.mock("sonner", () => ({
  toast: { success: (...a: unknown[]) => mockToastSuccess(...a), error: vi.fn() },
}));
vi.mock("@/components/auth/auth-guard", () => ({ useUser: () => ({ user: null }) }));

describe("newPasswordError", () => {
  it("enforces the minimum length and matching confirmation", () => {
    expect(newPasswordError("short", "short")).toMatch(/at least 8 characters/);
    expect(newPasswordError("longenough1", "longenough2")).toMatch(/do not match/);
    expect(newPasswordError("longenough1", "longenough1")).toBeNull();
  });
});

describe("normalizeMobile", () => {
  it("accepts Indian mobiles with optional prefix and rejects the rest", () => {
    expect(normalizeMobile("")).toBe("");
    expect(normalizeMobile("  ")).toBe("");
    expect(normalizeMobile("98765 43210")).toBe("9876543210");
    expect(normalizeMobile("+91-9876543210")).toBe("+919876543210");
    expect(normalizeMobile("12345")).toBeNull();
    expect(normalizeMobile("5876543210")).toBeNull();
    expect(normalizeMobile("abcdefghij")).toBeNull();
  });
});

describe("ChangePasswordSection", () => {
  beforeEach(() => {
    mockUpdateUser.mockReset();
    mockToastSuccess.mockReset();
  });

  const openAndFill = (password: string, confirmation: string) => {
    fireEvent.click(screen.getByTestId("profile.password.open"));
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: password } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: confirmation },
    });
    fireEvent.click(screen.getByTestId("profile.password.save"));
  };

  it("shows validation errors without calling Supabase", () => {
    render(<ChangePasswordSection />);
    openAndFill("abc", "abc");
    expect(screen.getByRole("alert")).toHaveTextContent(/at least 8 characters/);
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it("updates the password and collapses on success", async () => {
    mockUpdateUser.mockResolvedValue({ error: null });
    render(<ChangePasswordSection />);
    openAndFill("NewPassw0rd!", "NewPassw0rd!");
    await waitFor(() => expect(mockUpdateUser).toHaveBeenCalledWith({ password: "NewPassw0rd!" }));
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalled());
    expect(screen.getByTestId("profile.password.open")).toBeInTheDocument();
  });

  it("surfaces the Supabase error and stays open", async () => {
    mockUpdateUser.mockResolvedValue({
      error: { message: "New password should be different from the old password." },
    });
    render(<ChangePasswordSection />);
    openAndFill("SamePassw0rd", "SamePassw0rd");
    expect(await screen.findByRole("alert")).toHaveTextContent(/should be different/);
    expect(screen.getByTestId("profile.password.form")).toBeInTheDocument();
  });
});
