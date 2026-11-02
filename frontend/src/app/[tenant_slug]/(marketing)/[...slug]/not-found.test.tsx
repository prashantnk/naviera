// frontend/src/app/[tenant_slug]/(marketing)/[...slug]/not-found.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CatchAll404Page from "./page";
import MarketingNotFound from "./not-found";

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("next/navigation", () => ({ notFound: () => notFound() }));

vi.mock("@/components/providers/tenant-provider", () => ({
  // Subdomain routing: routeTo("/") is "/" (no tenant prefix).
  useTenant: () => ({ routeTo: (path: string) => path }),
}));

describe("marketing catch-all 404", () => {
  it("throws notFound() so the response is a real HTTP 404", () => {
    expect(() => CatchAll404Page()).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(1);
  });

  it("links home through routeTo (works on subdomain tenants)", () => {
    render(<MarketingNotFound />);
    expect(screen.getByRole("heading", { level: 1, name: "Page Not Found" })).toBeInTheDocument();
    expect(screen.getByTestId("not-found.home-link")).toHaveAttribute("href", "/");
  });
});
