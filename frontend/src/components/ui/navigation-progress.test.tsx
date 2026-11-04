// frontend/src/components/ui/navigation-progress.test.tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import Link from "next/link";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  NavigationProgress,
  triggerNavigationProgress,
} from "./navigation-progress";

let mockPathname = "/logismart-test/dashboard";
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useSearchParams: () => mockSearchParams,
}));

describe("NavigationProgress (< 16ms universal click acknowledgment)", () => {
  beforeEach(() => {
    mockPathname = "/logismart-test/dashboard";
    mockSearchParams = new URLSearchParams();
  });

  it("acknowledges clicks on internal <a> links synchronously in the capture phase and clears on route change", () => {
    const { rerender } = render(
      <div>
        <NavigationProgress />
        <Link
          href="/logismart-test/pickup-requests"
          data-testid="pickup-link"
        >
          Pickup Requests
        </Link>
      </div>
    );

    const progress = screen.getByTestId("global-navigation-progress");
    expect(progress.getAttribute("data-active")).toBe("false");
    expect(screen.queryByTestId("nav-ack-indicator")).toBeNull();

    const link = screen.getByTestId("pickup-link");
    fireEvent.click(link);

    expect(progress.getAttribute("data-active")).toBe("true");
    expect(screen.getByTestId("nav-ack-indicator")).toBeTruthy();
    expect(link.getAttribute("data-nav-pending")).toBe("true");

    // Simulate route settling
    mockPathname = "/logismart-test/pickup-requests";
    rerender(
      <div>
        <NavigationProgress />
        <Link
          href="/logismart-test/pickup-requests"
          data-testid="pickup-link"
        >
          Pickup Requests
        </Link>
      </div>
    );

    expect(progress.getAttribute("data-active")).toBe("false");
    expect(screen.queryByTestId("nav-ack-indicator")).toBeNull();
    expect(link.getAttribute("data-nav-pending")).toBeNull();
  });

  it("acknowledges clicks on [data-nav-trigger] elements and programmatic triggerNavigationProgress calls", () => {
    render(
      <div>
        <NavigationProgress />
        <button
          type="button"
          data-testid="quick-trigger"
          data-nav-trigger="/logismart-test/address-book"
        >
          Addresses
        </button>
      </div>
    );

    const progress = screen.getByTestId("global-navigation-progress");
    const triggerBtn = screen.getByTestId("quick-trigger");

    fireEvent.click(triggerBtn);
    expect(progress.getAttribute("data-active")).toBe("true");
    expect(triggerBtn.getAttribute("data-nav-pending")).toBe("true");

    act(() => {
      triggerNavigationProgress("/logismart-test/settings/addresses");
    });
    expect(progress.getAttribute("data-active")).toBe("true");
  });
});
