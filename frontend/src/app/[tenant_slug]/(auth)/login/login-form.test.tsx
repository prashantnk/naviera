// frontend/src/app/[tenant_slug]/(auth)/login/login-form.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LEGAL_PATHS } from "@/lib/legal";
import {
  LoginForm,
  MIN_PASSWORD_LENGTH,
  OTP_NO_ACCOUNT_MESSAGE,
  PENDING_PASSWORD_RESET_KEY,
  SET_PASSWORD_CALLBACK_INTENT,
  SIGNUP_CONSENT_REQUIRED_MESSAGE,
  consumePendingPasswordReset,
  otpRequestErrorMessage,
} from "./login-form";

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({
    tenantSlug: "logismart-test",
    routeTo: (path: string) => `/logismart-test${path}`,
    tenant: { id: "t1", name: "Logismart Test", slug: "logismart-test", settings: {} },
  }),
}));

const signInWithOtp = vi.fn();
const signOut = vi.fn(async () => ({}));
const routerReplace = vi.fn();
let storedSession: { access_token: string } | null = null;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: routerReplace }),
  useSearchParams: () => new URLSearchParams("next=/wallet"),
}));

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({
    auth: {
      getSession: async () => ({ data: { session: storedSession } }),
      signInWithOtp: (args: unknown) => signInWithOtp(args),
      signOut: () => signOut(),
    },
  }),
  resetSupabaseClient: vi.fn(),
}));

describe("LoginForm signup consent (C-08)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => vi.unstubAllGlobals());

  function openSignup() {
    render(<LoginForm />);
    fireEvent.click(screen.getByTestId("tab-signup"));
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "new@seller.in" },
    });
    fireEvent.change(screen.getByLabelText(/Create password/), {
      target: { value: "Secret-123" },
    });
  }

  it("uses a neutral full-name placeholder (A5-24)", () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByTestId("tab-signup"));
    expect(screen.getByLabelText("Full name")).toHaveAttribute("placeholder", "Your full name");
  });

  it("links the consent text to the Terms and Privacy pages in a new tab", () => {
    openSignup();
    const terms = screen.getByRole("link", { name: "Terms" });
    const privacy = screen.getByRole("link", { name: "Privacy Policy" });
    expect(terms).toHaveAttribute("href", `/logismart-test${LEGAL_PATHS.terms}`);
    expect(privacy).toHaveAttribute("href", `/logismart-test${LEGAL_PATHS.privacy}`);
    expect(terms).toHaveAttribute("target", "_blank");
    expect(screen.getByTestId("signup-terms-checkbox")).toBeRequired();
  });

  it("links 'prohibited items' in the consent text to the prohibited-items page", () => {
    openSignup();
    const prohibited = screen.getByRole("link", { name: "prohibited items" });
    expect(prohibited).toHaveAttribute("href", `/logismart-test${LEGAL_PATHS.prohibited}`);
    expect(prohibited).toHaveAttribute("target", "_blank");
  });

  it("rejects passwords shorter than 8 characters (B-05)", async () => {
    expect(MIN_PASSWORD_LENGTH).toBe(8);
    openSignup();
    fireEvent.change(screen.getByLabelText(/Create password/), {
      target: { value: "short77" },
    });
    fireEvent.click(screen.getByTestId("signup-terms-checkbox"));
    fireEvent.submit(screen.getByTestId("submit-create-account").closest("form")!);
    expect(
      await screen.findByText("Password must be at least 8 characters.")
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not call the API until the checkbox is ticked", async () => {
    openSignup();
    fireEvent.submit(screen.getByTestId("submit-create-account").closest("form")!);
    expect(await screen.findByText(SIGNUP_CONSENT_REQUIRED_MESSAGE)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends terms_accepted=true once the checkbox is ticked", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ loc: ["body", "email"], msg: "Field required" }] }),
    });
    openSignup();
    fireEvent.click(screen.getByTestId("signup-terms-checkbox"));
    fireEvent.submit(screen.getByTestId("submit-create-account").closest("form")!);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/users/auth/signup");
    expect(JSON.parse(init.body)).toMatchObject({
      email: "new@seller.in",
      terms_accepted: true,
    });
    // F-08: a 422 array becomes a readable, field-named message.
    expect(await screen.findByText("Email: Field required")).toBeInTheDocument();
  });
});

describe("LoginForm Email OTP never creates accounts (C-08 consent)", () => {
  beforeEach(() => signInWithOtp.mockReset());

  it("requests the OTP with shouldCreateUser=false and explains an unknown email", async () => {
    signInWithOtp.mockResolvedValue({
      error: { code: "otp_disabled", message: "Signups not allowed for otp" },
    });
    render(<LoginForm />);
    fireEvent.click(screen.getByTestId("tab-otp"));
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "stranger@example.invalid" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Send 6-Digit OTP" }).closest("form")!);

    expect(await screen.findByText(OTP_NO_ACCOUNT_MESSAGE)).toBeInTheDocument();
    expect(signInWithOtp).toHaveBeenCalledWith(
      expect.objectContaining({
        email: "stranger@example.invalid",
        options: expect.objectContaining({ shouldCreateUser: false }),
      }),
    );
    fireEvent.click(screen.getByTestId("otp-no-account-signup"));
    expect(screen.getByTestId("tab-signup")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("signup-terms-checkbox")).toBeInTheDocument();
  });

  it("otpRequestErrorMessage keeps other Supabase errors as-is", () => {
    expect(otpRequestErrorMessage({ message: "Signups not allowed for otp" })).toBe(OTP_NO_ACCOUNT_MESSAGE);
    expect(otpRequestErrorMessage({ code: "over_email_send_rate_limit", message: "Too many emails" })).toBe(
      "Too many emails",
    );
  });

  it("Set or Forgot Password saves pending password in sessionStorage and sets intent=set_password on callback URL", async () => {
    window.sessionStorage.clear();
    signInWithOtp.mockResolvedValue({ error: null });
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Set or Forgot Password?" }));
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "Existing@Seller.in" },
    });
    fireEvent.change(screen.getByLabelText(/New password/), {
      target: { value: "BrandNewPass-88" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Send Code to Set Password" }).closest("form")!
    );

    await waitFor(() => expect(signInWithOtp).toHaveBeenCalledTimes(1));
    expect(signInWithOtp).toHaveBeenCalledWith(
      expect.objectContaining({
        email: "Existing@Seller.in",
        options: expect.objectContaining({
          shouldCreateUser: false,
          emailRedirectTo: expect.stringContaining(
            `/logismart-test/callback?intent=${SET_PASSWORD_CALLBACK_INTENT}&next=%2Fwallet`
          ),
        }),
      })
    );
    expect(window.sessionStorage.getItem(PENDING_PASSWORD_RESET_KEY)).toBe(
      JSON.stringify({ email: "existing@seller.in", password: "BrandNewPass-88" })
    );
    expect(consumePendingPasswordReset("EXISTING@SELLER.IN")).toBe("BrandNewPass-88");
    expect(window.sessionStorage.getItem(PENDING_PASSWORD_RESET_KEY)).toBeNull();
  });
});

describe("LoginForm existing-session check", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    signOut.mockClear();
    routerReplace.mockReset();
    storedSession = { access_token: "jwt" };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    storedSession = null;
  });

  it("sends a signed-in user straight to ?next=", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200 });
    render(<LoginForm />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/logismart-test/wallet"));
  });

  it("keeps the session on a 5xx (backend restart) and signs out on 401", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 502 });
    const { unmount } = render(<LoginForm />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(signOut).not.toHaveBeenCalled();
    unmount();

    fetchMock.mockResolvedValue({ ok: false, status: 401 });
    render(<LoginForm />);
    await waitFor(() => expect(signOut).toHaveBeenCalledTimes(1));
  });
});
