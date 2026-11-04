// frontend/src/components/blocks/public-blocks.test.tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ERROR_FALLBACK_TITLE, ErrorFallback } from "./error-fallback";
import { FOOTER_LEGAL_LINKS, Footer, resolveSocialLinks } from "./footer";
import { FeaturesSection } from "./features-section";
import {
  DEFAULT_SHOWCASE_SLIDES,
  HeroSection,
  SHOWCASE_ROTATION_MS,
  resolveShowcaseSlides,
} from "./hero-section";
import { LEGAL_PATHS } from "@/lib/legal";

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenant_slug: "logismart-test" }),
  usePathname: () => "/logismart-test",
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
}));

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({
    auth: { getSession: async () => ({ data: { session: null } }) },
  }),
}));

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

describe("FeaturesSection client names (C-15) & Dual-Engine Architecture", () => {
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
    expect(screen.getByTestId("dual-engine-section")).toBeInTheDocument();
    expect(screen.getByTestId("operational-workflow-section")).toBeInTheDocument();
    expect(screen.getByTestId("marketing-cta-banner")).toBeInTheDocument();
  });

  it("renders no client wall when the tenant configured none", () => {
    render(<FeaturesSection content={{ headline: "Why us", features: [] }} />);
    expect(screen.queryByText("Clients")).not.toBeInTheDocument();
  });
});

describe("HeroSection 4-slide auto-rotating showcase (no stacked images)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders 4 slide tabs and strictly one active image inside the viewport", () => {
    render(
      <HeroSection
        title="International & Domestic Courier & Cargo Services"
        subtitle="Air, Cargo, Train & Transport."
        ctaText="Book Your Shipment"
        ctaLink="/shipments/new"
        badge="Logismart Pvt. Ltd."
        trustPartners={["DHL", "Blue Dart"]}
      />,
    );

    const viewport = screen.getByTestId("hero-showcase-viewport");
    const renderedImages = viewport.querySelectorAll("img");
    expect(renderedImages).toHaveLength(1);

    const tabs = [
      screen.getByTestId("hero-showcase-tab-0"),
      screen.getByTestId("hero-showcase-tab-1"),
      screen.getByTestId("hero-showcase-tab-2"),
      screen.getByTestId("hero-showcase-tab-3"),
    ];
    expect(tabs).toHaveLength(4);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute(
      "src",
      DEFAULT_SHOWCASE_SLIDES[0].fallbackSrc,
    );
    expect(screen.getByTestId("hero-showcase-title")).toHaveTextContent(
      DEFAULT_SHOWCASE_SLIDES[0].title,
    );
  });

  it("switches active slide when clicking slide tabs or prev/next controls", () => {
    render(
      <HeroSection
        title="International & Domestic Courier & Cargo Services"
        subtitle="Air, Cargo, Train & Transport."
        ctaText="Book Your Shipment"
        ctaLink="/shipments/new"
      />,
    );

    fireEvent.click(screen.getByTestId("hero-showcase-tab-2"));
    expect(screen.getByTestId("hero-showcase-tab-2")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("hero-showcase-title")).toHaveTextContent(
      DEFAULT_SHOWCASE_SLIDES[2].title,
    );
    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute(
      "src",
      DEFAULT_SHOWCASE_SLIDES[2].fallbackSrc,
    );

    fireEvent.click(screen.getByTestId("hero-showcase-next"));
    expect(screen.getByTestId("hero-showcase-tab-3")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute(
      "src",
      DEFAULT_SHOWCASE_SLIDES[3].fallbackSrc,
    );

    fireEvent.click(screen.getByTestId("hero-showcase-prev"));
    expect(screen.getByTestId("hero-showcase-tab-2")).toHaveAttribute("aria-selected", "true");
  });

  it("auto-advances slides on timer and pauses while hovered", () => {
    vi.useFakeTimers();
    render(
      <HeroSection
        title="International & Domestic Courier & Cargo Services"
        subtitle="Air, Cargo, Train & Transport."
        ctaText="Book Your Shipment"
        ctaLink="/shipments/new"
      />,
    );

    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute("data-slide-index", "0");

    act(() => {
      vi.advanceTimersByTime(SHOWCASE_ROTATION_MS);
    });
    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute("data-slide-index", "1");

    const showcase = screen.getByTestId("hero-showcase");
    fireEvent.mouseEnter(showcase);
    act(() => {
      vi.advanceTimersByTime(SHOWCASE_ROTATION_MS * 2);
    });
    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute("data-slide-index", "1");

    fireEvent.mouseLeave(showcase);
    act(() => {
      vi.advanceTimersByTime(SHOWCASE_ROTATION_MS);
    });
    expect(screen.getByTestId("hero-showcase-image")).toHaveAttribute("data-slide-index", "2");
  });

  it("upgrades legacy bento seed URLs and /images/showcase/*.svg paths to inline data-URI SVGs while supporting custom tenant overrides", () => {
    for (const slide of DEFAULT_SHOWCASE_SLIDES) {
      expect(slide.fallbackSrc.startsWith("data:image/svg+xml;utf8,")).toBe(true);
    }

    const legacy = resolveShowcaseSlides([
      "https://images.unsplash.com/photo-1542296332-2e4473faf563?q=80&w=2070",
      "https://images.unsplash.com/photo-1601584115197-04ecc0da31d7?q=80&w=2070",
      "https://images.unsplash.com/photo-9999999999-any-unsplash-url",
      "/images/showcase/wallet-gst-billing.svg",
    ]);
    expect(legacy.map((s) => s.imageSrc)).toEqual(
      DEFAULT_SHOWCASE_SLIDES.map((s) => s.fallbackSrc),
    );

    const custom = resolveShowcaseSlides(["/custom-slide-1.svg"]);
    expect(custom[0].imageSrc).toBe("/custom-slide-1.svg");
    expect(custom[1].imageSrc).toBe(DEFAULT_SHOWCASE_SLIDES[1].fallbackSrc);
  });

  it("reuses the single persistent <img> DOM node across slide rotations (zero unmount/remount)", () => {
    render(
      <HeroSection
        title="International & Domestic Courier & Cargo Services"
        subtitle="Air, Cargo, Train & Transport."
        ctaText="Book Your Shipment"
        ctaLink="/shipments/new"
      />,
    );

    const imgBefore = screen.getByTestId("hero-showcase-image");
    fireEvent.click(screen.getByTestId("hero-showcase-tab-1"));
    fireEvent.click(screen.getByTestId("hero-showcase-tab-2"));
    fireEvent.click(screen.getByTestId("hero-showcase-tab-3"));
    fireEvent.click(screen.getByTestId("hero-showcase-tab-0"));
    const imgAfter = screen.getByTestId("hero-showcase-image");
    expect(imgAfter).toBe(imgBefore);
  });
});
