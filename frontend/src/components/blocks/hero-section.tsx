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
  CheckCircle2,
  LayoutDashboard,
  MapPin,
  PackageSearch,
  PlaneTakeoff,
  ShieldCheck,
  UserCircle2,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

interface HeroSectionProps {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
  trustPartners?: string[];
  layoutVariant?: "saas" | "logistics_bento";
  images?: string[];
}

/**
 * Renders a partner name set by the tenant in `landing_page` settings as plain,
 * neutral text (C-15). No third-party logos, colours or trade dress are
 * hard-coded here: the tenant is responsible for every name it lists.
 */
function PartnerName({ name }: { name: string }) {
  return (
    <div className="text-xl font-bold text-slate-400 hover:text-slate-700 tracking-tight uppercase transition-colors cursor-default">
      {name}
    </div>
  );
}

export function HeroSection({
  title,
  subtitle,
  ctaText,
  ctaLink,
  badge,
  trustPartners = [],
  layoutVariant = "logistics_bento",
  images = [],
}: HeroSectionProps) {
  const { routeTo } = useTenant();
  const router = useRouter();
  const pathname = usePathname();
  const [trackingId, setTrackingId] = useState("");

  const params = useParams();
  const tenantSlug = (params?.tenant_slug as string) || "naviera";
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  // 🔥 NEW: Independent Staggered Timers for each Bento Box
  const [idx1, setIdx1] = useState(0);
  const [idx2, setIdx2] = useState(0);
  const [idx3, setIdx3] = useState(0);

  useEffect(() => {
    // Prime numbers for intervals so they rarely cross-fade at the exact same moment!
    const t1 = setInterval(() => setIdx1((prev) => (prev + 1) % 2), 5000);
    const t2 = setInterval(() => setIdx2((prev) => (prev + 1) % 2), 7000);
    const t3 = setInterval(() => setIdx3((prev) => (prev + 1) % 2), 9000);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
      clearInterval(t3);
    };
  }, []);

  // Split images into pairs for the 3 boxes
  const box1Images = [
    images[0] ||
      "https://images.unsplash.com/photo-1542296332-2e4473faf563?q=80&w=2070",
    images[3] ||
      "https://images.unsplash.com/photo-1587293852726-70cdb56c2866?q=80&w=2070",
  ];
  const box2Images = [
    images[1] ||
      "https://images.unsplash.com/photo-1601584115197-04ecc0da31d7?q=80&w=2070",
    images[4] ||
      "https://images.unsplash.com/photo-1519003722824-194d4455a60c?q=80&w=2070",
  ];
  const box3Images = [
    images[2] ||
      "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070",
    images[5] ||
      "https://images.unsplash.com/photo-1553413077-190dd305871c?q=80&w=2070",
  ];

  useEffect(() => {
    const checkAuth = async () => {
      const supabase = getSupabaseClient(tenantSlug);
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (session) setIsLoggedIn(true);
    };
    checkAuth();
  }, [tenantSlug]);

  const handleTrack = (e: React.FormEvent) => {
    e.preventDefault();
    const normalized = normalizeTrackingId(trackingId);
    if (normalized) router.push(routeTo(`/track/${encodeURIComponent(normalized)}`));
  };

  return (
    <div className="flex flex-col relative overflow-hidden bg-white">
      <div className="absolute top-0 right-0 w-full md:w-1/2 h-full bg-slate-50 skew-x-12 translate-x-32 border-l border-slate-100/50 pointer-events-none" />
      <div
        className="absolute left-0 top-0 w-full max-w-3xl h-[600px] blur-[120px] rounded-full pointer-events-none"
        style={{
          backgroundColor: "color-mix(in srgb, var(--primary) 5%, transparent)",
        }}
      />

      <section className="relative pt-16 pb-20 lg:pt-24 lg:pb-32 z-10">
        <div className="container mx-auto px-4 md:px-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-16 items-center">
            {/* ⬅️ LEFT COLUMN: Text Content */}
            <div className="lg:col-span-6 flex flex-col justify-center space-y-8 relative z-20">
              <div className="space-y-6">
                {badge && (
                  <div className="inline-flex items-center rounded-full bg-slate-50 border border-slate-200 px-4 py-1.5 text-sm font-bold text-slate-700 shadow-sm animate-in fade-in slide-in-from-bottom-4 duration-700">
                    <ShieldCheck
                      className="h-4 w-4 mr-2"
                      style={{ color: "var(--primary)" }}
                    />
                    {badge}
                  </div>
                )}
                <h1 className="text-3xl sm:text-5xl lg:text-[4.5rem] font-extrabold tracking-tighter text-slate-900 leading-[1.08] sm:leading-[1.05] animate-in fade-in slide-in-from-bottom-6 duration-700 delay-100">
                  <span
                    className="bg-clip-text text-transparent"
                    style={{
                      backgroundImage:
                        "linear-gradient(to bottom right, var(--secondary), #1e293b)",
                    }}
                  >
                    {title.split(".")[0]}.
                  </span>
                  <br />
                  {title.split(".").slice(1).join(".")}
                </h1>
                <p className="max-w-[550px] text-lg lg:text-xl text-slate-600 font-medium leading-relaxed animate-in fade-in slide-in-from-bottom-6 duration-700 delay-200">
                  {subtitle}
                </p>
              </div>

              {/* CTAs */}
              <div className="flex flex-col sm:flex-row gap-4 pt-2 animate-in fade-in duration-700 delay-300">
                {isLoggedIn ? (
                  <Button
                    size="lg"
                    asChild
                    className="h-16 px-8 rounded-xl text-lg font-bold bg-primary text-primary-foreground hover:opacity-90 shadow-xl shadow-primary/20 group"
                  >
                    <Link href={routeTo("/dashboard")}>
                      <LayoutDashboard className="mr-2 h-6 w-6" /> Go to
                      Dashboard
                      <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </Link>
                  </Button>
                ) : (
                  <Button
                    size="lg"
                    asChild
                    className="h-16 px-8 rounded-xl text-lg font-bold bg-primary text-primary-foreground hover:opacity-90 shadow-xl shadow-primary/20 group"
                  >
                    <Link
                      href={`${routeTo("/login")}?next=${encodeURIComponent(
                        pathname
                      )}`}
                    >
                      <UserCircle2 className="mr-2 h-6 w-6" /> Customer Login
                      <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </Link>
                  </Button>
                )}
                <Button
                  size="lg"
                  variant="outline"
                  asChild
                  className="h-16 px-8 rounded-xl text-lg font-bold border-2 border-slate-200 hover:bg-slate-50"
                >
                  <Link href={routeTo(ctaLink)}>{ctaText}</Link>
                </Button>
              </div>

              {/* Tracking Widget */}
              <div className="bg-white p-2.5 rounded-2xl border border-slate-200 w-full max-w-[550px] shadow-lg animate-in fade-in zoom-in-95 duration-700 delay-500 mt-4">
                <form
                  onSubmit={handleTrack}
                  className="flex flex-col sm:flex-row gap-2 relative"
                >
                  <div className="relative flex-1">
                    <div className="absolute left-4 top-0 bottom-0 flex items-center justify-center">
                      <PackageSearch className="h-6 w-6 text-slate-400" />
                    </div>
                    <Input
                      placeholder={TRACKING_INPUT_PLACEHOLDER}
                      aria-label="AWB / tracking number"
                      autoCapitalize="characters"
                      className="h-14 pl-12 bg-slate-50 border-transparent text-slate-900 text-lg shadow-inner uppercase placeholder:normal-case"
                      value={trackingId}
                      onChange={(e) => setTrackingId(e.target.value)}
                    />
                  </div>
                  <Button
                    type="submit"
                    size="lg"
                    className="h-14 px-10 rounded-xl text-lg font-bold shadow-md hover:scale-[1.02] transition-transform text-white"
                    style={{ backgroundColor: "var(--secondary)" }}
                  >
                    Track
                  </Button>
                </form>
              </div>

              {/* 🔥 FIX 1: Super Slow, Elegant Marquee with Pause on Hover */}
              {trustPartners.length > 0 && (
                <div className="pt-6 mt-4 border-t border-slate-200/60 max-w-xl animate-in fade-in duration-700 delay-700 relative">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-5">
                    Our partners
                  </p>
                  <div className="flex overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_10%,black_90%,transparent)]">
                    <div
                      className="flex shrink-0 animate-marquee items-center gap-12 pr-12 hover:[animation-play-state:paused]"
                      style={{ animationDuration: "80s" }}
                    >
                      {[
                        ...trustPartners,
                        ...trustPartners,
                        ...trustPartners,
                      ].map((partner, i) => (
                        <PartnerName key={`${partner}-${i}`} name={partner} />
                      ))}
                    </div>
                    <div
                      className="flex shrink-0 animate-marquee items-center gap-12 pr-12 hover:[animation-play-state:paused]"
                      aria-hidden="true"
                      style={{ animationDuration: "80s" }}
                    >
                      {[
                        ...trustPartners,
                        ...trustPartners,
                        ...trustPartners,
                      ].map((partner, i) => (
                        <PartnerName
                          key={`${partner}-copy-${i}`}
                          name={partner}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ➡️ RIGHT COLUMN: Dynamic Visual Composition (Balanced Bento Grid) */}
            <div className="lg:col-span-6 relative w-full h-[440px] sm:h-[520px] lg:h-[560px] animate-in fade-in slide-in-from-right-12 duration-1000 delay-300 mt-12 lg:mt-0">
              <div
                className="absolute inset-4 sm:inset-10 blur-[60px] sm:blur-[80px] rounded-full opacity-80 z-0 pointer-events-none"
                style={{
                  backgroundColor:
                    "color-mix(in srgb, var(--secondary) 10%, transparent)",
                }}
              />

              {layoutVariant === "logistics_bento" ? (
                <div className="relative z-10 grid grid-cols-12 grid-rows-2 gap-4 sm:gap-5 w-full h-full">
                  {/* TOP WIDE SHOWCASE CARD (Box 1: Air Cargo — Full 12 Columns, Row 1) */}
                  <div className="col-span-12 row-span-1 relative group">
                    <div className="w-full h-full bg-white p-1.5 sm:p-2 rounded-[1.5rem] sm:rounded-[2rem] shadow-xl border border-slate-100 transform group-hover:scale-[1.01] transition-transform duration-500 flex flex-col">
                      <div className="relative w-full h-full rounded-[1.25rem] sm:rounded-[1.5rem] overflow-hidden bg-slate-100">
                        {box1Images.map((src, idx) => (
                          <img
                            key={idx}
                            src={src}
                            alt="Air Cargo"
                            className={cn(
                              "absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ease-in-out",
                              idx === idx1 ? "opacity-100" : "opacity-0"
                            )}
                          />
                        ))}
                      </div>
                    </div>

                    {/* Spacious Floating Card 1: Live Air Cargo Route (Top-Left Corner) */}
                    <div
                      className="absolute -top-5 left-2 sm:-left-6 z-30 animate-float"
                      style={{ animationDelay: "1.5s" }}
                    >
                      <div className="bg-white/95 backdrop-blur-xl px-3.5 py-3 sm:px-5 sm:py-4 rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.14)] border border-slate-100 w-[255px] sm:w-[310px]">
                        <div className="flex items-center justify-between mb-2.5 sm:mb-3 border-b border-slate-100 pb-2 sm:pb-2.5">
                          <span className="text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-widest flex items-center gap-1.5 whitespace-nowrap">
                            <PlaneTakeoff
                              className="h-3.5 w-3.5 shrink-0"
                              style={{ color: "var(--primary)" }}
                            />
                            Live Air Cargo
                          </span>
                          <span className="flex h-2.5 w-2.5 rounded-full bg-green-500 animate-ping shrink-0" />
                        </div>
                        <div className="flex items-center justify-between gap-2 sm:gap-3">
                          <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
                            <div className="h-7 w-7 sm:h-8 sm:w-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center shrink-0">
                              <MapPin className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-slate-600" />
                            </div>
                            <div className="whitespace-nowrap">
                              <p className="text-xs sm:text-sm font-bold text-slate-900 leading-tight whitespace-nowrap">
                                New Delhi
                              </p>
                              <p className="text-[9px] sm:text-[10px] text-slate-400 uppercase font-semibold whitespace-nowrap">
                                Origin
                              </p>
                            </div>
                          </div>

                          <div
                            className="flex-1 border-t-2 border-dashed min-w-[16px] sm:min-w-[24px]"
                            style={{
                              borderColor:
                                "color-mix(in srgb, var(--primary) 45%, transparent)",
                            }}
                          />

                          <div className="flex items-center gap-2 sm:gap-2.5 text-right shrink-0">
                            <div className="whitespace-nowrap">
                              <p className="text-xs sm:text-sm font-bold text-slate-900 leading-tight whitespace-nowrap">
                                New York
                              </p>
                              <p
                                className="text-[9px] sm:text-[10px] uppercase font-bold whitespace-nowrap"
                                style={{ color: "var(--secondary)" }}
                              >
                                In Transit
                              </p>
                            </div>
                            <div
                              className="h-7 w-7 sm:h-8 sm:w-8 rounded-full border flex items-center justify-center shrink-0"
                              style={{
                                backgroundColor:
                                  "color-mix(in srgb, var(--secondary) 10%, transparent)",
                                borderColor:
                                  "color-mix(in srgb, var(--secondary) 20%, transparent)",
                              }}
                            >
                              <CheckCircle2
                                className="h-3.5 w-3.5 sm:h-4 sm:w-4"
                                style={{ color: "var(--secondary)" }}
                              />
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* BOTTOM-LEFT BALANCED CARD (Box 3: Warehousing — 6 Columns, Row 2) */}
                  <div className="col-span-6 row-span-1 relative group">
                    <div className="w-full h-full bg-white p-1.5 sm:p-2 rounded-[1.5rem] sm:rounded-[2rem] shadow-xl border border-slate-100 transform group-hover:scale-[1.01] transition-transform duration-500 flex flex-col">
                      <div className="relative w-full h-full rounded-[1.25rem] sm:rounded-[1.5rem] overflow-hidden bg-slate-100">
                        {box3Images.map((src, idx) => (
                          <img
                            key={idx}
                            src={src}
                            alt="Warehousing"
                            className={cn(
                              "absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ease-in-out",
                              idx === idx3 ? "opacity-100" : "opacity-0"
                            )}
                          />
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* BOTTOM-RIGHT BALANCED CARD (Box 2: Surface Transport — 6 Columns, Row 2) */}
                  <div className="col-span-6 row-span-1 relative group">
                    <div className="w-full h-full bg-white p-1.5 sm:p-2 rounded-[1.5rem] sm:rounded-[2rem] shadow-xl border border-slate-100 transform group-hover:scale-[1.01] transition-transform duration-500 flex flex-col">
                      <div className="relative w-full h-full rounded-[1.25rem] sm:rounded-[1.5rem] overflow-hidden bg-slate-100">
                        {box2Images.map((src, idx) => (
                          <img
                            key={idx}
                            src={src}
                            alt="Surface Transport"
                            className={cn(
                              "absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ease-in-out",
                              idx === idx2 ? "opacity-100" : "opacity-0"
                            )}
                          />
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Floating Badge 2: Delivery Rate (Bottom-Left on Mobile to avoid WhatsApp FAB, Bottom-Right on Desktop) */}
                  <div
                    className="absolute -bottom-4 left-2 sm:left-auto sm:right-5 z-30 animate-float"
                    style={{ animationDelay: "0.5s" }}
                  >
                    <div className="bg-white/95 backdrop-blur-xl px-3.5 py-2.5 sm:px-4 sm:py-3 rounded-2xl shadow-[0_16px_40px_rgba(0,0,0,0.12)] border border-slate-100 flex items-center gap-2.5 sm:gap-3.5 whitespace-nowrap">
                      <div className="h-9 w-9 sm:h-11 sm:w-11 rounded-full bg-green-100 border border-green-200 flex items-center justify-center shrink-0">
                        <CheckCircle2 className="h-4 w-4 sm:h-6 sm:w-6 text-green-600" />
                      </div>
                      <div>
                        <p className="text-[9px] sm:text-xs font-bold text-slate-400 uppercase tracking-wider whitespace-nowrap">
                          Delivery Rate
                        </p>
                        <p className="text-lg sm:text-2xl font-black text-slate-900 tracking-tight leading-none mt-0.5 whitespace-nowrap">
                          99.8%
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                /* SAAS LAYOUT */
                <div className="absolute inset-4 sm:inset-10 bg-white p-2 rounded-[2rem] shadow-2xl z-10 border border-slate-100 transform hover:-rotate-1 transition-all duration-500">
                  <img
                    src={box1Images[0]}
                    alt="Platform Dashboard"
                    className="w-full h-full object-cover rounded-[1.5rem]"
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
