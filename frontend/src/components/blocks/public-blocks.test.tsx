// frontend/src/components/blocks/public-blocks.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ERROR_FALLBACK_TITLE, ErrorFallback } from "./error-fallback";
import { FOOTER_LEGAL_LINKS, Footer, resolveSocialLinks } from "./footer";
import { FeaturesSection } from "./features-section";
import { LEGAL_PATHS } from "@/lib/legal";

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({
    tenant: { id: "t1", name: "Logismart Test", slug: "logismart-test", settings: {} },
    routeTo: (path: string) => `/logismart-test${path}`,
  }),
}));

describe("ErrorFallback (F-08 / F-12)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is neutral, logs the error with its digest, and retries", () => {
    const logSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const onRetry = vi.fn();
    const error = Object.assign(new Error("boom"), { digest: "abc123" });
    render(<ErrorFallback error={error} onRetry={onRetry} source="tenant" />);

    expect(screen.getByRole("heading", { name: ERROR_FALLBACK_TITLE })).toBeInTheDocument();
    expect(screen.getByRole("alert")).not.toHaveTextContent(/database|Naviera/i);
    expect(screen.getByText("Reference: abc123")).toBeInTheDocument();
    expect(logSpy).toHaveBeenCalledWith("[error-boundary:tenant]", "abc123", error);

    fireEvent.click(screen.getByTestId("error-fallback.retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("Footer legal links (C-08)", () => {
  it("links every policy page through routeTo", () => {
    render(<Footer />);
    const nav = screen.getByTestId("footer.legal-links");
    expect(FOOTER_LEGAL_LINKS.map((l) => l.href)).toEqual([
      LEGAL_PATHS.terms,
      LEGAL_PATHS.privacy,
      LEGAL_PATHS.refund,
      LEGAL_PATHS.prohibited,
      LEGAL_PATHS.grievance,
    ]);
    for (const link of FOOTER_LEGAL_LINKS) {
      const anchor = Array.from(nav.querySelectorAll("a")).find((a) => a.textContent === link.label);
      expect(anchor).toHaveAttribute("href", `/logismart-test${link.href}`);
    }
  });

  it("hides the Follow Us column when no social profile is configured (no dead '#' links)", () => {
    render(<Footer />);
    expect(screen.queryByTestId("footer.socials")).not.toBeInTheDocument();
    expect(document.querySelector('a[href="#"]')).toBeNull();
  });

  it("resolveSocialLinks keeps only configured profiles, in display order", () => {
    const links = resolveSocialLinks({ linkedin: " https://linkedin.com/x ", facebook: "", youtube: undefined });
    expect(links.map(({ label, url }) => ({ label, url }))).toEqual([
      { label: "LinkedIn", url: "https://linkedin.com/x" },
    ]);
    expect(resolveSocialLinks(undefined)).toEqual([]);
  });
});

describe("FeaturesSection client names (C-15)", () => {
  it("renders tenant-configured names as plain text without brand colours", () => {
    render(
      <FeaturesSection
        content={{
          headline: "Why us",
          features: [],
          clientsHeadline: "Clients",
          clientLogos: [{ name: "Acme Traders", color: "#ff0000" }],
        }}
      />,
    );
    const names = screen.getAllByText("Acme Traders");
    expect(names.length).toBeGreaterThan(0);
    expect(names[0]).not.toHaveAttribute("style");
  });

  it("renders no client wall when the tenant configured none", () => {
    render(<FeaturesSection content={{ headline: "Why us", features: [] }} />);
    expect(screen.queryByText("Clients")).not.toBeInTheDocument();
  });
});
