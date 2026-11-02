// frontend/src/components/pricing-admin/notice-banner.tsx
/**
 * A plain-English status banner used across the pricing admin screens
 * (e.g. "COD is OFF for all customers until you set both values").
 */
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Visual tone of a banner. */
export enum NoticeTone {
  WARNING = "WARNING",
  SUCCESS = "SUCCESS",
  INFO = "INFO",
}

const TONE_CLASSES: Readonly<Record<NoticeTone, string>> = {
  [NoticeTone.WARNING]: "border-amber-200 bg-amber-50 text-amber-900",
  [NoticeTone.SUCCESS]: "border-emerald-200 bg-emerald-50 text-emerald-900",
  [NoticeTone.INFO]: "border-slate-200 bg-slate-50 text-slate-700",
};

const TONE_ICONS = {
  [NoticeTone.WARNING]: AlertTriangle,
  [NoticeTone.SUCCESS]: CheckCircle2,
  [NoticeTone.INFO]: Info,
} as const;

interface NoticeBannerProps {
  tone: NoticeTone;
  title: string;
  children?: ReactNode;
  testId?: string;
}

/**
 * Renders one status banner.
 *
 * @param tone - Warning, success or info styling.
 * @param title - The one-line message.
 * @param children - Optional explanation under the title.
 * @param testId - `data-testid` for UI journeys.
 */
export function NoticeBanner({ tone, title, children, testId }: NoticeBannerProps) {
  const Icon = TONE_ICONS[tone];
  return (
    <div
      role={tone === NoticeTone.WARNING ? "alert" : "status"}
      data-testid={testId}
      className={cn("flex items-start gap-3 rounded-xl border px-4 py-3 text-xs", TONE_CLASSES[tone])}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-0.5">
        <p className="font-bold">{title}</p>
        {children && <div className="leading-relaxed opacity-90">{children}</div>}
      </div>
    </div>
  );
}
