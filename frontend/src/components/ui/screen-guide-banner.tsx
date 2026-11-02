// frontend/src/components/ui/screen-guide-banner.tsx
"use client";

/**
 * Role-aware 3-step contextual "How this screen works" guide strip with a
 * Delhivery One equivalent badge and persistent dismissal (`localStorage`).
 *
 * When dismissed, collapses into a compact `"How it works ?"` pill button
 * mirroring `one.delhivery.com`'s header helper pill so staff or customers can
 * reopen the guide anytime without cluttering their daily workspace.
 */
import { CircleHelp, Compass, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const STORAGE_PREFIX = "logismart-guide-dismissed:";

/** One numbered step inside the screen guide banner. */
export interface GuideStep {
  title: string;
  description: string;
}

export interface ScreenGuideBannerProps {
  /** Stable identifier used for testids and `localStorage` dismissal key. */
  guideId: string;
  /** Default heading (shown to customers or when `staffTitle` is omitted). */
  title: string;
  /** Optional heading shown when `isStaff` is true. */
  staffTitle?: string;
  /** Badge explaining the `one.delhivery.com` equivalent screen/workflow. */
  delhiveryEquivalent: string;
  /** Steps shown to customers (or everyone when `staffSteps` is omitted). */
  steps: readonly GuideStep[];
  /** Optional steps shown when `isStaff` is true. */
  staffSteps?: readonly GuideStep[];
  /** Whether the active viewer is a Logismart staff/admin member. */
  isStaff?: boolean;
}

/**
 * Reads whether a guide has been dismissed in `localStorage`.
 *
 * @param guideId - Unique guide identifier.
 * @returns True when previously dismissed by the user.
 */
function _readDismissed(guideId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(`${STORAGE_PREFIX}${guideId}`) === "1";
  } catch {
    return false;
  }
}

/**
 * Persists or clears the dismissal flag in `localStorage`.
 *
 * @param guideId - Unique guide identifier.
 * @param dismissed - Whether the banner should be hidden.
 */
function _writeDismissed(guideId: string, dismissed: boolean): void {
  if (typeof window === "undefined") return;
  try {
    const key = `${STORAGE_PREFIX}${guideId}`;
    if (dismissed) {
      window.localStorage.setItem(key, "1");
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Ignore storage quota / private-browsing restrictions
  }
}

/**
 * Renders a dismissible 3-step quick-guide banner or its compact "How it works ?" reopen pill.
 */
export function ScreenGuideBanner({
  guideId,
  title,
  staffTitle,
  delhiveryEquivalent,
  steps,
  staffSteps,
  isStaff = false,
}: ScreenGuideBannerProps) {
  const [dismissed, setDismissed] = useState<boolean>(() => _readDismissed(guideId));

  useEffect(() => {
    setDismissed(_readDismissed(guideId));
  }, [guideId]);

  const activeSteps = isStaff && staffSteps && staffSteps.length > 0 ? staffSteps : steps;
  const activeTitle = isStaff && staffTitle ? staffTitle : title;

  const handleDismiss = () => {
    _writeDismissed(guideId, true);
    setDismissed(true);
  };

  const handleReopen = () => {
    _writeDismissed(guideId, false);
    setDismissed(false);
  };

  if (dismissed) {
    return (
      <div className="flex items-center justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleReopen}
          data-testid={`screen-guide.${guideId}.reopen`}
          className="h-7 gap-1.5 rounded-full border-primary/25 bg-primary/5 px-3 text-xs font-semibold text-primary hover:bg-primary/10"
        >
          <CircleHelp className="h-3.5 w-3.5" aria-hidden />
          <span>How it works</span>
        </Button>
      </div>
    );
  }

  return (
    <section
      aria-label={activeTitle}
      data-testid={`screen-guide.${guideId}`}
      className="rounded-xl border border-primary/20 bg-primary/5 p-4 shadow-2xs"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Compass className="h-3.5 w-3.5" aria-hidden />
          </span>
          <h2 className="text-xs font-extrabold tracking-wide text-foreground uppercase">
            {activeTitle}
          </h2>
          <Badge
            variant="outline"
            className="border-primary/30 bg-card text-[11px] font-semibold text-primary"
          >
            {delhiveryEquivalent}
          </Badge>
          {isStaff && (
            <Badge
              variant="outline"
              className="border-border bg-muted text-[10px] font-bold text-muted-foreground"
            >
              Staff / Admin View
            </Badge>
          )}
        </div>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleDismiss}
          data-testid={`screen-guide.${guideId}.dismiss`}
          className="h-7 self-end px-2 text-xs font-semibold text-muted-foreground hover:text-foreground sm:self-auto"
          aria-label="Hide quick guide"
        >
          <span className="mr-1">Hide guide</span>
          <X className="h-3.5 w-3.5" aria-hidden />
        </Button>
      </div>

      <ol className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        {activeSteps.map((step, index) => (
          <li
            key={step.title}
            className="flex items-start gap-2.5 rounded-lg border border-border bg-card p-3"
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-extrabold text-primary">
              {index + 1}
            </span>
            <div className="min-w-0 space-y-0.5">
              <p className="text-xs font-bold text-foreground">{step.title}</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {step.description}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
