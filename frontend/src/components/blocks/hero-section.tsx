// frontend/src/components/blocks/hero-section.tsx
"use client";

import {
  TRACKING_INPUT_PLACEHOLDER,
  normalizeTrackingId,
} from "@/components/blocks/tracking-display";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getSupabaseClient } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import {
  ArrowRight,
  Boxes,
  Calculator,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  PackageCheck,
  PackageSearch,
  ReceiptText,
  ScanLine,
  ShieldCheck,
  Truck,
  UserCircle2,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useProgressRouter } from "@/hooks/use-progress-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  B2B_CARGO_FLEET_DATA_URI,
  B2C_EXPRESS_DATA_URI,
  HUB_SORTATION_DATA_URI,
  SHOWCASE_SVG_DATA_URIS,
  WALLET_GST_BILLING_DATA_URI,
} from "./showcase-svgs";

export interface HeroSectionProps {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
  trustPartners?: string[];
  layoutVariant?: "saas" | "logistics_bento";
  images?: string[];
}

export interface ShowcaseSlide {
  id: string;
  step: string;
  tabLabel: string;
  category: string;
  title: string;
  subtitle: string;
  metricLabel: string;
  metricValue: string;
  highlights: string[];
  imageSrc: string;
  fallbackSrc: string;
  Icon: LucideIcon;
}

/** Auto-advance interval for the 4-slide homepage showcase carousel. */
export const SHOWCASE_ROTATION_MS = 4500;

/**
 * Legacy Unsplash seed URLs from earlier bento builds. When a tenant's
 * `landing_page` config still holds only these default URLs, we upgrade
 * seamlessly to the 4 curated local showcase visuals so offline/online
 * rendering is 100% deterministic with zero external 404s.
 */
const LEGACY_BENTO_IMAGE_PREFIXES: ReadonlyArray<string> = [
  "https://images.unsplash.com/photo-1542296332-2e4473faf563",
  "https://images.unsplash.com/photo-1601584115197-04ecc0da31d7",
  "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d",
  "https://images.unsplash.com/photo-1587293852726-70cdb56c2866",
  "https://images.unsplash.com/photo-1519003722824-194d4455a60c",
  "https://images.unsplash.com/photo-1553413077-190dd305871c",
];

/** Default 4-slide showcase definition (Delhivery One parity pillars, inline zero-network SVGs). */
export const DEFAULT_SHOWCASE_SLIDES: ReadonlyArray<Omit<ShowcaseSlide, "imageSrc">> = [
  {
    id: "b2c-express",
    step: "01",
    tabLabel: "B2C Express",
    category: "B2C EXPRESS PARCEL",
    title: "B2C Express Parcel Fulfillment",
    subtitle:
      "Same-day & next-day doorstep pickup, thermal 4×6\" shipping labels, barcode scan, and consignee OTP-verified delivery.",
    metricLabel: "First-Attempt SLA",
    metricValue: "99.8% On-Time",
    highlights: ["Doorstep OTP POD", "Prepaid & COD", "29,000+ PIN Codes"],
    fallbackSrc: B2C_EXPRESS_DATA_URI,
    Icon: PackageCheck,
  },
  {
    id: "b2b-cargo-fleet",
    step: "02",
    tabLabel: "B2B Cargo",
    category: "B2B HEAVY CARGO & FLEET",
    title: "B2B Heavy Cargo & PTL/FTL Fleet",
    subtitle:
      "Multi-box Lorry Receipts (LR), master & child box labels, E-Way Bill verification, and dock-to-dock or door delivery across India.",
    metricLabel: "Cargo Network",
    metricValue: "PTL & FTL Pan-India",
    highlights: ["Multi-Box LRs", "ROV / FOV Cover", "Appointment Delivery"],
    fallbackSrc: B2B_CARGO_FLEET_DATA_URI,
    Icon: Truck,
  },
  {
    id: "hub-sortation",
    step: "03",
    tabLabel: "Hub Sortation",
    category: "HUB SORTATION & CONTROL TOWER",
    title: "Automated Hub Sortation & Dimensioning",
    subtitle:
      "Laser volumetric & dead-weight audit with sorter photo proof, plus a real-time NDR & exception control tower.",
    metricLabel: "Weight & NDR Audit",
    metricValue: "100% Photo Verified",
    highlights: ["Laser Dim-Scan", "NDR Re-Attempt Queue", "72h E-Way Watchdog"],
    fallbackSrc: HUB_SORTATION_DATA_URI,
    Icon: ScanLine,
  },
  {
    id: "wallet-gst-billing",
    step: "04",
    tabLabel: "Wallet & Billing",
    category: "UNIFIED WALLET & COMPLIANCE",
    title: "Unified Wallet, COD Remittance & GST Billing",
    subtitle:
      "Instant UPI wallet recharge, automated bank NEFT/IMPS COD settlement batches, and sequential FY-scoped GST invoices & notes.",
    metricLabel: "Compliance Engine",
    metricValue: "SAC 996812 / 996511",
    highlights: ["Instant UPI Credit", "T+2 COD Remittance", "18% GST Split"],
    fallbackSrc: WALLET_GST_BILLING_DATA_URI,
    Icon: ReceiptText,
  },
];

export function isLegacyBentoImage(url: string): boolean {
  const trimmed = url.trim().toLowerCase();
  return (
    trimmed.includes("images.unsplash.com") ||
    LEGACY_BENTO_IMAGE_PREFIXES.some((prefix) =>
      trimmed.startsWith(prefix.toLowerCase())
    )
  );
}

/**
 * Resolves the 4 showcase slides, combining curated zero-network inline SVG visuals
 * with any custom non-legacy tenant `landing_page` image overrides.
 */
export function resolveShowcaseSlides(images?: string[]): ShowcaseSlide[] {
  const validCustom = (images || [])
    .map((img) => (typeof img === "string" ? img.trim() : ""))
    .filter(
      (img) =>
        Boolean(img) && !isLegacyBentoImage(img) && !SHOWCASE_SVG_DATA_URIS[img]
    );

  return DEFAULT_SHOWCASE_SLIDES.map((slide, index) => ({
    ...slide,
    imageSrc: validCustom[index] || slide.fallbackSrc,
  }));
}

/**
 * Renders a partner name set by the tenant in `landing_page` settings as plain,
 * neutral text (C-15). No third-party logos, colours or trade dress are
 * hard-coded here: the tenant is responsible for every name it lists.
 */
function PartnerName({ name }: { name: string }) {
  return (
    <div className="px-3.5 py-1.5 rounded-lg bg-slate-100/80 border border-slate-200/80 text-xs sm:text-sm font-bold text-slate-600 tracking-wider uppercase transition-colors">
      {name}
    </div>
  );
}

const HERO_KPIS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "29,000+", label: "Serviceable PINs" },
  { value: "99.8%", label: "First-Attempt SLA" },
  { value: "PTL & FTL", label: "Heavy Cargo LRs" },
  { value: "T+2 Days", label: "COD Remittance" },
];

export function HeroSection({
  title,
  subtitle,
  ctaText,
  ctaLink,
  badge,
  trustPartners = [],
  images = [],
}: HeroSectionProps) {
  const { routeTo } = useTenant();
  const router = useProgressRouter();
  const pathname = usePathname();
  const [trackingId, setTrackingId] = useState("");

  const params = useParams();
  const tenantSlug = (params?.tenant_slug as string) || "naviera";
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const slides = useMemo(() => resolveShowcaseSlides(images), [images]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const [failedImages, setFailedImages] = useState<Record<string, boolean>>({});

  const slideCount = slides.length;

  const goToNext = useCallback(() => {
    setActiveIndex((prev) => (prev + 1) % slideCount);
  }, [slideCount]);

  const goToPrev = useCallback(() => {
    setActiveIndex((prev) => (prev - 1 + slideCount) % slideCount);
  }, [slideCount]);

  useEffect(() => {
    if (isPaused || slideCount <= 1) return undefined;
    const timer = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % slideCount);
    }, SHOWCASE_ROTATION_MS);
    return () => clearInterval(timer);
  }, [isPaused, slideCount]);

  // Pre-warm any custom non-data-URI slide images once on mount so slide rotation
  // never triggers network fetches.
  useEffect(() => {
    if (typeof window === "undefined") return;
    for (const slide of slides) {
      if (slide.imageSrc && !slide.imageSrc.startsWith("data:")) {
        const preloader = new window.Image();
        preloader.src = slide.imageSrc;
      }
    }
  }, [slides]);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const supabase = getSupabaseClient(tenantSlug);
        const {
          data: { session },
        } = await supabase.auth.getSession();
        if (session) setIsLoggedIn(true);
      } catch {
        setIsLoggedIn(false);
      }
    };
    void checkAuth();
  }, [tenantSlug]);

  const handleTrack = (e: React.FormEvent) => {
    e.preventDefault();
    const normalized = normalizeTrackingId(trackingId);
    if (normalized) {
      router.push(routeTo(`/track/${encodeURIComponent(normalized)}`));
    }
  };

  const activeSlide = slides[activeIndex] || slides[0];
  const activeImgSrc = failedImages[activeSlide.id]
    ? activeSlide.fallbackSrc
    : activeSlide.imageSrc;
  const ActiveIcon = activeSlide.Icon;

  const titleParts = title.split(".");
  const headlineLead = titleParts[0] ? `${titleParts[0]}.` : title;
  const headlineRest = titleParts.slice(1).join(".").trim();

  return (
    <div className="flex flex-col relative overflow-hidden bg-gradient-to-b from-slate-50 via-white to-white border-b border-slate-200/70">
      {/* Subtle architectural background grid & brand glow */}
      <div
        className="absolute -top-32 -left-32 w-[520px] h-[520px] blur-[130px] rounded-full pointer-events-none"
        style={{
          backgroundColor: "color-mix(in srgb, var(--primary) 8%, transparent)",
        }}
      />
      <div
        className="absolute top-16 right-0 w-[480px] h-[480px] blur-[140px] rounded-full pointer-events-none"
        style={{
          backgroundColor:
            "color-mix(in srgb, var(--secondary) 8%, transparent)",
        }}
      />

      <section className="relative pt-10 pb-16 lg:pt-16 lg:pb-24 z-10">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-start">
            {/* LEFT COLUMN: Executive Value Proposition, Tracking Command Bar & CTAs */}
            <div className="lg:col-span-6 flex flex-col justify-center space-y-6 relative z-20">
              <div className="space-y-4">
                <div className="inline-flex flex-wrap items-center gap-2 rounded-full bg-white border border-slate-200 px-3.5 py-1.5 text-xs sm:text-sm font-bold text-slate-800 shadow-sm w-fit">
                  <ShieldCheck
                    className="h-4 w-4 shrink-0"
                    style={{ color: "var(--primary)" }}
                  />
                  <span>{badge || "Enterprise 3PL & 4PL Logistics"}</span>
                  <span className="hidden sm:inline-block text-slate-300">|</span>
                  <span className="hidden sm:inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    B2C Express &amp; B2B Cargo
                  </span>
                </div>

                <h1 className="text-3xl sm:text-5xl lg:text-[3.5rem] font-extrabold tracking-tight text-slate-950 leading-[1.1]">
                  <span
                    className="bg-clip-text text-transparent"
                    style={{
                      backgroundImage:
                        "linear-gradient(to bottom right, var(--secondary), #0f172a)",
                    }}
                  >
                    {headlineLead}
                  </span>
                  {headlineRest && (
                    <>
                      {" "}
                      <span className="text-slate-900">{headlineRest}</span>
                    </>
                  )}
                </h1>

                <p className="max-w-xl text-base sm:text-lg text-slate-600 font-medium leading-relaxed">
                  {subtitle}
                </p>
              </div>

              {/* Live Consignee AWB / LR Tracking Bar */}
              <div className="bg-white p-2 sm:p-2.5 rounded-2xl border border-slate-200/90 w-full max-w-xl shadow-md">
                <form
                  onSubmit={handleTrack}
                  data-testid="hero-tracking-form"
                  className="flex flex-col sm:flex-row gap-2"
                >
                  <div className="relative flex-1 min-w-0">
                    <div className="absolute left-3.5 top-0 bottom-0 flex items-center justify-center pointer-events-none">
                      <PackageSearch className="h-5 w-5 text-slate-400" />
                    </div>
                    <Input
                      placeholder={TRACKING_INPUT_PLACEHOLDER}
                      aria-label="AWB / tracking number"
                      autoCapitalize="characters"
                      className="h-12 sm:h-13 pl-11 bg-slate-50 border-slate-200/80 text-slate-900 text-sm sm:text-base font-medium uppercase placeholder:normal-case"
                      value={trackingId}
                      onChange={(e) => setTrackingId(e.target.value)}
                    />
                  </div>
                  <Button
                    type="submit"
                    size="lg"
                    className="h-12 sm:h-13 px-7 rounded-xl text-base font-bold shadow-sm text-white shrink-0"
                    style={{ backgroundColor: "var(--secondary)" }}
                  >
                    Track Shipment
                  </Button>
                </form>
              </div>

              {/* Primary & Secondary Action Buttons + Rate Calculator Quick Links */}
              <div className="space-y-3 pt-1">
                <div className="flex flex-col sm:flex-row gap-3">
                  {isLoggedIn ? (
                    <Button
                      size="lg"
                      asChild
                      className="h-13 px-6 rounded-xl text-base font-bold bg-primary text-primary-foreground hover:opacity-90 shadow-lg shadow-primary/20 group"
                    >
                      <Link href={routeTo("/dashboard")}>
                        <LayoutDashboard className="mr-2 h-5 w-5" /> Go to
                        Dashboard
                        <ArrowRight className="ml-2 h-4 w-4 group-hover:translate-x-1 transition-transform" />
                      </Link>
                    </Button>
                  ) : (
                    <Button
                      size="lg"
                      asChild
                      className="h-13 px-6 rounded-xl text-base font-bold bg-primary text-primary-foreground hover:opacity-90 shadow-lg shadow-primary/20 group"
                    >
                      <Link
                        href={`${routeTo("/login")}?next=${encodeURIComponent(
                          pathname
                        )}`}
                      >
                        <UserCircle2 className="mr-2 h-5 w-5" /> Customer Login
                        <ArrowRight className="ml-2 h-4 w-4 group-hover:translate-x-1 transition-transform" />
                      </Link>
                    </Button>
                  )}
                  <Button
                    size="lg"
                    variant="outline"
                    asChild
                    className="h-13 px-6 rounded-xl text-base font-bold border-2 border-slate-200 bg-white hover:bg-slate-50 text-slate-900"
                  >
                    <Link href={routeTo(ctaLink)}>{ctaText}</Link>
                  </Button>
                </div>

                {/* Quick Utility Pills */}
                <div className="flex flex-wrap items-center gap-2 pt-1 text-xs font-semibold text-slate-600">
                  <Link
                    href={routeTo("/rate-calculator")}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 text-slate-700 transition-colors"
                  >
                    <Calculator className="h-3.5 w-3.5 text-primary" />
                    B2C Rate Calculator
                  </Link>
                  <Link
                    href={routeTo("/b2b/rate-calculator")}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 text-slate-700 transition-colors"
                  >
                    <Boxes className="h-3.5 w-3.5 text-primary" />
                    B2B Cargo Calculator
                  </Link>
                  <Link
                    href={routeTo("/services")}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 text-slate-700 transition-colors"
                  >
                    <Truck className="h-3.5 w-3.5 text-primary" />
                    Explore Services
                  </Link>
                </div>
              </div>

              {/* 4-Metric Network Telemetry Strip */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-2">
                {HERO_KPIS.map((kpi) => (
                  <div
                    key={kpi.label}
                    className="rounded-xl bg-white border border-slate-200/80 px-3.5 py-2.5 shadow-xs"
                  >
                    <p className="text-base sm:text-lg font-extrabold text-slate-900 tracking-tight">
                      {kpi.value}
                    </p>
                    <p className="text-[11px] font-semibold text-slate-500">
                      {kpi.label}
                    </p>
                  </div>
                ))}
              </div>

              {/* Carrier & Enterprise Partners Strip (C-15 plain text) */}
              {trustPartners.length > 0 && (
                <div className="pt-3 border-t border-slate-200/70">
                  <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2.5">
                    Carrier &amp; Network Partners
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    {trustPartners.map((partner, i) => (
                      <PartnerName key={`${partner}-${i}`} name={partner} />
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* RIGHT COLUMN: Single-Frame 4-Image Auto-Rotating Showcase Carousel (Zero Stacked Images) */}
            <div className="lg:col-span-6 w-full">
              <div
                data-testid="hero-showcase"
                role="region"
                aria-roledescription="carousel"
                aria-label="Logistics Operations Showcase"
                onMouseEnter={() => setIsPaused(true)}
                onMouseLeave={() => setIsPaused(false)}
                onFocusCapture={() => setIsPaused(true)}
                onBlurCapture={() => setIsPaused(false)}
                className="rounded-3xl bg-white border border-slate-200/90 shadow-xl overflow-hidden flex flex-col"
              >
                {/* Top Control & Telemetry Header Bar */}
                <div className="px-4 sm:px-6 py-3.5 bg-slate-900 text-white flex items-center justify-between gap-3 border-b border-slate-800">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 shrink-0" />
                    <span
                      data-testid="hero-showcase-step"
                      className="text-xs font-mono font-bold text-slate-300 uppercase tracking-wider truncate"
                    >
                      {activeSlide.step} / 0{slideCount} · {activeSlide.category}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <div
                      data-testid="hero-showcase-metric"
                      className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-800 border border-slate-700 text-xs font-bold text-emerald-400"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                      <span>{activeSlide.metricValue}</span>
                    </div>

                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        data-testid="hero-showcase-prev"
                        aria-label="Previous slide"
                        onClick={goToPrev}
                        className="h-8 w-8 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 flex items-center justify-center text-slate-200 transition-colors cursor-pointer"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        data-testid="hero-showcase-next"
                        aria-label="Next slide"
                        onClick={goToNext}
                        className="h-8 w-8 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 flex items-center justify-center text-slate-200 transition-colors cursor-pointer"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>

                {/* Single-Frame Image Viewport (Strictly ONE persistent <img> rendered, zero stacked/overlapping images, zero remounts) */}
                <div
                  data-testid="hero-showcase-viewport"
                  className="relative w-full aspect-[16/10] bg-slate-950 overflow-hidden flex items-center justify-center"
                >
                  <img
                    data-testid="hero-showcase-image"
                    data-slide-index={activeIndex}
                    src={activeImgSrc}
                    alt={activeSlide.title}
                    decoding="sync"
                    loading="eager"
                    onError={() => {
                      if (!failedImages[activeSlide.id]) {
                        setFailedImages((prev) => ({
                          ...prev,
                          [activeSlide.id]: true,
                        }));
                      }
                    }}
                    className="w-full h-full object-contain sm:object-cover block transition-opacity duration-300"
                  />
                </div>

                {/* Active Slide Caption & Operational Highlights */}
                <div className="p-4 sm:p-6 bg-white border-t border-slate-100 space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <div
                          className="h-7 w-7 rounded-lg flex items-center justify-center shrink-0"
                          style={{
                            backgroundColor:
                              "color-mix(in srgb, var(--primary) 12%, white)",
                            color: "var(--primary)",
                          }}
                        >
                          <ActiveIcon className="h-4 w-4" />
                        </div>
                        <h2
                          data-testid="hero-showcase-title"
                          className="text-lg sm:text-xl font-extrabold text-slate-900 tracking-tight truncate"
                        >
                          {activeSlide.title}
                        </h2>
                      </div>
                      <p
                        data-testid="hero-showcase-subtitle"
                        className="text-xs sm:text-sm text-slate-600 leading-relaxed"
                      >
                        {activeSlide.subtitle}
                      </p>
                    </div>
                  </div>

                  {/* Operational Highlight Pills */}
                  <div className="flex flex-wrap items-center gap-2">
                    {activeSlide.highlights.map((item) => (
                      <span
                        key={item}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-100 text-slate-700 text-xs font-semibold"
                      >
                        <CheckCircle2
                          className="h-3.5 w-3.5 shrink-0"
                          style={{ color: "var(--primary)" }}
                        />
                        {item}
                      </span>
                    ))}
                  </div>

                  {/* 4 Interactive Slide Selector Tabs */}
                  <div
                    role="tablist"
                    aria-label="Showcase slides"
                    className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-slate-100"
                  >
                    {slides.map((slide, index) => {
                      const isActive = index === activeIndex;
                      return (
                        <button
                          key={slide.id}
                          type="button"
                          role="tab"
                          aria-selected={isActive}
                          aria-label={`Slide ${index + 1}: ${slide.title}`}
                          data-testid={`hero-showcase-tab-${index}`}
                          onClick={() => setActiveIndex(index)}
                          className={cn(
                            "text-left px-3 py-2.5 rounded-xl border transition-all cursor-pointer flex flex-col gap-1 relative overflow-hidden",
                            isActive
                              ? "bg-slate-900 text-white border-slate-900 shadow-sm"
                              : "bg-slate-50 hover:bg-slate-100 text-slate-700 border-slate-200/80"
                          )}
                        >
                          <div
                            className="h-1 w-full rounded-full mb-0.5"
                            style={{
                              backgroundColor: isActive
                                ? "var(--primary)"
                                : "rgba(148, 163, 184, 0.35)",
                            }}
                          />
                          <span
                            className={cn(
                              "text-[10px] font-mono font-bold uppercase tracking-wider",
                              isActive ? "text-slate-300" : "text-slate-400"
                            )}
                          >
                            {slide.step}
                          </span>
                          <span className="text-xs font-bold truncate">
                            {slide.tabLabel}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
