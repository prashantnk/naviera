// frontend/src/components/ui/navigation-progress.test.tsx
/* eslint-disable @next/next/no-html-link-for-pages -- the bar must also handle plain <a> elements, not only next/link. */
import { act, fireEvent, render, screen } from "@testing-library/react";
import Link from "next/link";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MIN_VISIBLE_MS,
  NavigationProgress,
  SAFETY_TIMEOUT_MS,
  triggerNavigationProgress,
} from "./navigation-progress";

let mockPathname = "/logismart-test/dashboard";
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useSearchParams: () => mockSearchParams,
}));

/** Renders the bar next to `children`; bubbling clicks are cancelled so jsdom never navigates. */
function renderWithBar(children: ReactNode) {
  const tree = () => (
    <div onClick={(event) => event.preventDefault()}>
      <NavigationProgress />
      {children}
    </div>
  );
  const utils = render(tree());
  return { ...utils, rerenderBar: () => utils.rerender(tree()) };
}

function bar(): HTMLElement {
  return screen.getByTestId("global-navigation-progress");
}

describe("NavigationProgress (< 16ms universal click acknowledgment)", () => {
  beforeEach(() => {
    mockPathname = "/logismart-test/dashboard";
    mockSearchParams = new URLSearchParams();
    window.history.replaceState(null, "", "/logismart-test/dashboard");
  });

  afterEach(() => {
    vi.useRealTimers();
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

  it("only flashes for a link to the current URL (cannot get stuck)", () => {
    vi.useFakeTimers();
    renderWithBar(
      <a href="/logismart-test/dashboard#orders" data-testid="same">
        Home
      </a>,
    );
    fireEvent.click(screen.getByTestId("same"));
    expect(bar().getAttribute("data-active")).toBe("true");
    act(() => {
      vi.advanceTimersByTime(MIN_VISIBLE_MS + 1);
    });
    expect(bar().getAttribute("data-active")).toBe("false");
    expect(screen.getByTestId("same").getAttribute("data-nav-pending")).toBeNull();
  });

  it.each([
    ["hash-only link", { href: "#section" }],
    ["new tab", { href: "/logismart-test/shipments", target: "_blank" }],
    ["download attribute", { href: "/logismart-test/shipments", download: "" }],
    ["external origin", { href: "https://example.com/x" }],
    ["rel=external", { href: "/logismart-test/shipments", rel: "external" }],
    ["API file download", { href: "/api/v1/shipments/s1/label" }],
    ["static file", { href: "/docs/rate-card.pdf" }],
    ["mailto", { href: "mailto:ops@logismart.in" }],
  ])("ignores %s", (_label, attrs) => {
    renderWithBar(
      <a data-testid="link" {...attrs}>
        Link
      </a>,
    );
    fireEvent.click(screen.getByTestId("link"));
    expect(bar().getAttribute("data-active")).toBe("false");
  });

  it.each([
    ["ctrl", { ctrlKey: true }],
    ["meta", { metaKey: true }],
    ["shift", { shiftKey: true }],
    ["alt", { altKey: true }],
    ["middle button", { button: 1 }],
  ])("ignores %s clicks (browser opens a new tab/window)", (_label, init) => {
    renderWithBar(
      <a href="/logismart-test/shipments" data-testid="link">
        Orders
      </a>,
    );
    fireEvent.click(screen.getByTestId("link"), init);
    expect(bar().getAttribute("data-active")).toBe("false");
  });

  it("auto-clears after the safety timeout when the route never changes", () => {
    vi.useFakeTimers();
    renderWithBar(
      <a href="/logismart-test/shipments" data-testid="link">
        Orders
      </a>,
    );
    fireEvent.click(screen.getByTestId("link"));
    act(() => {
      vi.advanceTimersByTime(SAFETY_TIMEOUT_MS - 1);
    });
    expect(bar().getAttribute("data-active")).toBe("true");
    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(bar().getAttribute("data-active")).toBe("false");
    expect(screen.getByTestId("link").getAttribute("data-nav-pending")).toBeNull();
  });

  it("settles on a search-param-only navigation", () => {
    const { rerenderBar } = renderWithBar(
      <a href="/logismart-test/dashboard?tab=RESOLVED" data-testid="link">
        Resolved
      </a>,
    );
    fireEvent.click(screen.getByTestId("link"));
    expect(bar().getAttribute("data-active")).toBe("true");
    mockSearchParams = new URLSearchParams("tab=RESOLVED");
    rerenderBar();
    expect(bar().getAttribute("data-active")).toBe("false");
  });

  it("shows the bar on back/forward only while the rendered route lags the address bar", () => {
    renderWithBar(null);
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(bar().getAttribute("data-active")).toBe("false");

    window.history.replaceState(null, "", "/logismart-test/wallet");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(bar().getAttribute("data-active")).toBe("true");
  });

  it("flashes for a programmatic trigger to the current URL", () => {
    vi.useFakeTimers();
    renderWithBar(null);
    act(() => {
      triggerNavigationProgress("/logismart-test/dashboard");
    });
    expect(bar().getAttribute("data-active")).toBe("true");
    act(() => {
      vi.advanceTimersByTime(MIN_VISIBLE_MS + 1);
    });
    expect(bar().getAttribute("data-active")).toBe("false");
  });

  it("leaves history untouched and removes its listeners on unmount", () => {
    const originalPushState = window.history.pushState;
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const { unmount } = renderWithBar(null);
    expect(window.history.pushState).toBe(originalPushState);
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("click", expect.any(Function), true);
    expect(window.history.pushState).toBe(originalPushState);
    removeSpy.mockRestore();
  });
});
