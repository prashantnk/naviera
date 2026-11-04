// frontend/src/components/blocks/features-section.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { ClientLogo, FeaturesBlockContent } from "@/types/tenant";
import {
  ArrowRight,
  Boxes,
  Calculator,
  CheckCircle2,
  ClipboardCheck,
  Globe2,
  MonitorSmartphone,
  PackageCheck,
  QrCode,
  ShoppingBag,
  Sparkles,
  Truck,
} from "lucide-react";
import Link from "next/link";

// Map string keys from the DB to actual React components safely
const iconMap: Record<string, React.ElementType> = {
  monitor: MonitorSmartphone,
  "shopping-bag": ShoppingBag,
  globe: Globe2,
  package: PackageCheck,
};

const DUAL_ENGINES = [
  {
    id: "b2c-engine",
    badge: "ENGINE 01 · B2C EXPRESS PARCELS",
    weightRange: "0.5 kg – 50 kg",
    title: "High-Velocity D2C & E-Commerce Express",
    description:
      "Built for fast-moving consumer shipments with same-day and next-day air/surface dispatch, doorstep OTP verification, and automated buyer notifications.",
    bullets: [
      "Same-Day & Next-Day Air / Surface Express Slabs",
      "Thermal 4×6\" Barcode Labels & Bulk CSV Booking",
      "Consignee OTP-Verified POD & Real-Time NDR Action Queue",
      "Prepaid Wallet & Automated T+2 Bank COD Remittance",
    ],
    primaryCta: { label: "Book Express Parcel", href: "/shipments/new/forward" },
    secondaryCta: { label: "B2C Rate Calculator", href: "/rate-calculator" },
    Icon: PackageCheck,
    darkCard: false,
  },
  {
    id: "b2b-engine",
    badge: "ENGINE 02 · B2B HEAVY CARGO (PTL / FTL)",
    weightRange: "50 kg – 20+ Tons",
    title: "Industrial Lorry Receipts & Multi-Box Freight",
    description:
      "Engineered for palletized wholesale, factory-to-warehouse linehaul, and multi-carton consignments with child box tracking and E-Way Bill governance.",
    bullets: [
      "Master LR + Multi-Box Child Labels & E-Way Bill Validation",
      "Logismart Prime Lanes, Door-to-Door & Godown Hold-for-Pickup",
      "Mall / CSD / Warehouse Appointment Delivery & Stamped POD",
      "Carrier ROV / FOV Transit Risk Cover & SAC 996511 GTA Billing",
    ],
    primaryCta: { label: "Book B2B Cargo LR", href: "/b2b/orders/new" },
    secondaryCta: { label: "B2B Cargo Calculator", href: "/b2b/rate-calculator" },
    Icon: Truck,
    darkCard: true,
  },
] as const;

const WORKFLOW_STEPS = [
  {
    step: "01",
    title: "Instant Rate & Serviceability Quote",
    description:
      "Enter origin & destination PIN codes, package dimensions, and declared value to preview live zone slabs, volumetric weight, and GST split.",
    Icon: Calculator,
  },
  {
    step: "02",
    title: "Book AWB / LR & Print Thermal Labels",
    description:
      "Confirm booking via prepaid wallet or COD with atomic ledger debit, sequential FY Tax Invoice issuance, and downloadable 4×6\" shipping labels.",
    Icon: QrCode,
  },
  {
    step: "03",
    title: "Scheduled Manifest Pickup & Hub Scan",
    description:
      "Group open orders into a warehouse truck pickup request (PUR) with automated hub laser dimensioning and 24/7 exception monitoring.",
    Icon: Boxes,
  },
  {
    step: "04",
    title: "OTP Delivery, COD Payout & GST Ledger",
    description:
      "Capture doorstep OTP or stamped LR POD, receive NEFT/IMPS COD remittances, and download compliant GST Invoices, Credit & Debit Notes.",
    Icon: ClipboardCheck,
  },
] as const;

/**
 * Renders a client name set by the tenant in `landing_page` settings as plain,
 * neutral text (C-15). No third-party logos, brand colours or trade dress are
 * hard-coded here: the tenant is responsible for every name it lists.
 */
function ClientName({ brand }: { brand: ClientLogo | string }) {
  // Handle both old string format and new object format gracefully
  const name = typeof brand === "string" ? brand : brand.name;
  return (
    <span className="text-2xl font-bold tracking-tight uppercase text-slate-500">
      {name}
    </span>
  );
}

export function FeaturesSection({
  content,
}: {
  content: FeaturesBlockContent;
}) {
  const { routeTo } = useTenant();

  return (
    <section className="py-16 lg:py-24 bg-white">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl space-y-24">
        {/* 1. Dual-Engine Service Architecture (B2C Express vs B2B Heavy Cargo) */}
        <div data-testid="dual-engine-section" className="space-y-10">
          <div className="text-center max-w-3xl mx-auto space-y-3">
            <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs font-bold uppercase tracking-widest text-slate-700">
              <Sparkles
                className="h-3.5 w-3.5"
                style={{ color: "var(--primary)" }}
              />
              Unified Logistics Operating System
            </div>
            <h2 className="text-2xl sm:text-4xl font-extrabold text-slate-950 tracking-tight">
              Two Purpose-Built Engines. One Control Tower.
            </h2>
            <p className="text-base sm:text-lg text-slate-600">
              Seamlessly dispatch D2C express parcels and multi-ton B2B Lorry
              Receipts from a single multi-warehouse workspace.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 lg:gap-8">
            {DUAL_ENGINES.map((engine) => {
              const EngineIcon = engine.Icon;
              const isDark = engine.darkCard;
              return (
                <div
                  key={engine.id}
                  data-testid={engine.id}
                  className={`rounded-3xl p-6 sm:p-8 lg:p-10 border flex flex-col justify-between gap-8 transition-shadow hover:shadow-xl ${
                    isDark
                      ? "bg-slate-900 border-slate-800 text-white"
                      : "bg-slate-50/80 border-slate-200/90 text-slate-900"
                  }`}
                >
                  <div className="space-y-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span
                        className={`text-xs font-mono font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${
                          isDark
                            ? "bg-slate-800 border-slate-700 text-slate-200"
                            : "bg-white border-slate-200 text-slate-700"
                        }`}
                      >
                        {engine.badge}
                      </span>
                      <span
                        className={`text-xs font-bold px-3 py-1 rounded-full ${
                          isDark
                            ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                            : "bg-emerald-50 text-emerald-700 border border-emerald-200"
                        }`}
                      >
                        {engine.weightRange}
                      </span>
                    </div>

                    <div className="flex items-start gap-4">
                      <div
                        className={`h-12 w-12 rounded-2xl flex items-center justify-center shrink-0 border ${
                          isDark
                            ? "bg-white/10 border-white/15 text-white"
                            : "bg-white border-slate-200 shadow-xs"
                        }`}
                      >
                        <EngineIcon
                          className="h-6 w-6"
                          style={!isDark ? { color: "var(--primary)" } : {}}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <h3
                          className={`text-xl sm:text-2xl font-extrabold tracking-tight ${
                            isDark ? "text-white" : "text-slate-900"
                          }`}
                        >
                          {engine.title}
                        </h3>
                        <p
                          className={`text-sm sm:text-base leading-relaxed ${
                            isDark ? "text-slate-300" : "text-slate-600"
                          }`}
                        >
                          {engine.description}
                        </p>
                      </div>
                    </div>

                    <ul className="space-y-2.5 pt-2">
                      {engine.bullets.map((item) => (
                        <li
                          key={item}
                          className={`flex items-start gap-2.5 text-sm font-medium ${
                            isDark ? "text-slate-200" : "text-slate-700"
                          }`}
                        >
                          <CheckCircle2
                            className="h-4 w-4 mt-0.5 shrink-0"
                            style={{
                              color: isDark ? "#4ade80" : "var(--primary)",
                            }}
                          />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-slate-200/20">
                    <Button
                      asChild
                      className={
                        isDark
                          ? "bg-primary text-primary-foreground hover:opacity-90 font-bold rounded-xl"
                          : "bg-slate-900 text-white hover:bg-slate-800 font-bold rounded-xl"
                      }
                    >
                      <Link href={routeTo(engine.primaryCta.href)}>
                        {engine.primaryCta.label}
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="outline"
                      asChild
                      className={
                        isDark
                          ? "border-slate-700 bg-slate-800/70 text-white hover:bg-slate-800 font-bold rounded-xl"
                          : "border-slate-300 bg-white text-slate-800 hover:bg-slate-100 font-bold rounded-xl"
                      }
                    >
                      <Link href={routeTo(engine.secondaryCta.href)}>
                        {engine.secondaryCta.label}
                      </Link>
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 2. Tenant-Configured Core Capabilities Grid */}
        <div className="space-y-12">
          <div className="text-center max-w-3xl mx-auto space-y-3">
            {content.badge && (
              <h2
                className="text-xs sm:text-sm font-bold tracking-widest uppercase"
                style={{ color: "var(--primary)" }}
              >
                {content.badge}
              </h2>
            )}
            <h3 className="text-2xl sm:text-4xl font-extrabold text-slate-900 tracking-tight">
              {content.headline}
            </h3>
            {content.subheadline && (
              <p className="text-base sm:text-lg text-slate-600">
                {content.subheadline}
              </p>
            )}
          </div>

          {content.features.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 lg:gap-8">
              {content.features.map((feature, index) => {
                const Icon = iconMap[feature.icon] || PackageCheck;
                const isAccentDark = index === 3;

                return (
                  <div
                    key={index}
                    className={`rounded-3xl p-6 sm:p-8 border transition-shadow hover:shadow-lg relative overflow-hidden ${
                      isAccentDark
                        ? "text-white border-slate-800 shadow-lg"
                        : "bg-white border-slate-200/90 text-slate-900 shadow-xs"
                    }`}
                    style={
                      isAccentDark
                        ? { backgroundColor: "var(--secondary)" }
                        : {}
                    }
                  >
                    <div className="relative z-10 space-y-4">
                      <div className="flex items-center gap-3.5">
                        <div
                          className={`h-12 w-12 rounded-2xl flex items-center justify-center shrink-0 border ${
                            isAccentDark
                              ? "bg-white/10 border-white/20 text-white"
                              : "bg-slate-50 border-slate-200"
                          }`}
                        >
                          <Icon
                            className="h-6 w-6"
                            style={
                              !isAccentDark ? { color: "var(--primary)" } : {}
                            }
                          />
                        </div>
                        <h4
                          className={`text-xl font-extrabold tracking-tight ${
                            isAccentDark ? "text-white" : "text-slate-900"
                          }`}
                        >
                          {feature.title}
                        </h4>
                      </div>

                      <p
                        className={`text-sm sm:text-base leading-relaxed ${
                          isAccentDark ? "text-slate-200" : "text-slate-600"
                        }`}
                      >
                        {feature.description}
                      </p>

                      {feature.bullets && feature.bullets.length > 0 && (
                        <ul
                          className={`grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2 text-xs sm:text-sm font-semibold ${
                            isAccentDark ? "text-slate-100" : "text-slate-700"
                          }`}
                        >
                          {feature.bullets.map((bullet, i) => (
                            <li key={i} className="flex items-center gap-2">
                              <CheckCircle2
                                className="h-4 w-4 shrink-0"
                                style={{
                                  color: isAccentDark
                                    ? "#4ade80"
                                    : "var(--primary)",
                                }}
                              />
                              <span>{bullet}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 3. 4-Step How-It-Works Operational Flow */}
        <div
          data-testid="operational-workflow-section"
          className="rounded-3xl bg-slate-50 border border-slate-200/80 p-6 sm:p-10 lg:p-12 space-y-10"
        >
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div className="space-y-2 max-w-2xl">
              <p
                className="text-xs font-bold uppercase tracking-widest"
                style={{ color: "var(--primary)" }}
              >
                End-to-End Dispatch Lifecycle
              </p>
              <h3 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
                From Instant Rate Quote to Doorstep POD &amp; GST Settlement
              </h3>
            </div>
            <Button
              variant="outline"
              asChild
              className="w-fit rounded-xl font-bold border-slate-300 bg-white hover:bg-slate-100"
            >
              <Link href={routeTo("/services")}>
                View All Logistics Services
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {WORKFLOW_STEPS.map((item) => {
              const StepIcon = item.Icon;
              return (
                <div
                  key={item.step}
                  className="rounded-2xl bg-white border border-slate-200/90 p-5 flex flex-col justify-between gap-4 shadow-xs"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span
                        className="text-xs font-mono font-extrabold px-2.5 py-1 rounded-md text-white"
                        style={{ backgroundColor: "var(--secondary)" }}
                      >
                        STEP {item.step}
                      </span>
                      <StepIcon
                        className="h-5 w-5"
                        style={{ color: "var(--primary)" }}
                      />
                    </div>
                    <h4 className="text-base font-extrabold text-slate-900 leading-snug">
                      {item.title}
                    </h4>
                    <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
                      {item.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 4. Client names configured in the tenant landing_page settings (C-15) */}
        {content.clientLogos && content.clientLogos.length > 0 && (
          <div className="border-t border-slate-200 pt-14">
            <div className="text-center mb-8">
              <h3 className="text-2xl font-bold text-slate-900">
                {content.clientsHeadline}
              </h3>
              <p className="text-slate-500 mt-1.5">
                {content.clientsSubheadline}
              </p>
            </div>

            <div className="flex overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_10%,black_90%,transparent)] py-4">
              <div
                className="flex shrink-0 animate-marquee items-center gap-16 pr-16 hover:[animation-play-state:paused]"
                style={{ animationDuration: "120s" }}
              >
                {[
                  ...content.clientLogos,
                  ...content.clientLogos,
                  ...content.clientLogos,
                ].map((logo, index) => (
                  <div
                    key={index}
                    className="hover:scale-105 transition-transform duration-300 cursor-default"
                  >
                    <ClientName brand={logo} />
                  </div>
                ))}
              </div>
              <div
                className="flex shrink-0 animate-marquee items-center gap-16 pr-16 hover:[animation-play-state:paused]"
                aria-hidden="true"
                style={{ animationDuration: "120s" }}
              >
                {[
                  ...content.clientLogos,
                  ...content.clientLogos,
                  ...content.clientLogos,
                ].map((logo, index) => (
                  <div
                    key={`copy-${index}`}
                    className="hover:scale-105 transition-transform duration-300 cursor-default"
                  >
                    <ClientName brand={logo} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 5. Executive Bottom Conversion CTA Banner */}
        <div
          data-testid="marketing-cta-banner"
          className="rounded-3xl p-8 sm:p-12 text-white flex flex-col lg:flex-row items-start lg:items-center justify-between gap-8 shadow-xl"
          style={{
            backgroundImage:
              "linear-gradient(135deg, #0f172a 0%, var(--secondary) 100%)",
          }}
        >
          <div className="space-y-2.5 max-w-2xl">
            <p className="text-xs font-mono font-bold uppercase tracking-widest text-emerald-400">
              Ready to Dispatch Today
            </p>
            <h3 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
              Start Shipping Express Parcels &amp; Heavy Cargo in Minutes
            </h3>
            <p className="text-sm sm:text-base text-slate-300 leading-relaxed">
              Create your shipper account, check live PIN serviceability and
              freight rates, or speak with our enterprise supply-chain desk.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 shrink-0">
            <Button
              size="lg"
              asChild
              className="h-12 px-6 rounded-xl font-bold bg-primary text-primary-foreground hover:opacity-90 shadow-lg"
            >
              <Link href={routeTo("/shipments/new/forward")}>
                Book a Shipment
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button
              size="lg"
              variant="outline"
              asChild
              className="h-12 px-6 rounded-xl font-bold border-slate-600 bg-slate-900/60 text-white hover:bg-slate-800"
            >
              <Link href={routeTo("/rate-calculator")}>Calculate Rates</Link>
            </Button>
            <Button
              size="lg"
              variant="outline"
              asChild
              className="h-12 px-6 rounded-xl font-bold border-slate-600 bg-slate-900/60 text-white hover:bg-slate-800"
            >
              <Link href={routeTo("/contact")}>Contact Sales</Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
