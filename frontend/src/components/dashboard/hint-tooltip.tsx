// frontend/src/components/dashboard/hint-tooltip.tsx
"use client";

import { cn } from "@/lib/utils";
import { useId } from "react";

interface HintTooltipProps {
  /** Text shown in the tooltip and announced to screen readers. */
  hint: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Small, dependency-free tooltip (CSS hover / keyboard focus).
 *
 * The trigger is focusable and points at the tooltip via `aria-describedby`,
 * so keyboard and screen-reader users get the same hint as mouse users.
 * Do NOT nest inside a link or button (interactive content inside interactive
 * content is invalid HTML).
 */
export function HintTooltip({ hint, children, className }: HintTooltipProps) {
  const tooltipId = useId();
  return (
    <span
      tabIndex={0}
      aria-describedby={tooltipId}
      className={cn(
        "group relative inline-flex cursor-help items-center rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
    >
      {children}
      <span
        role="tooltip"
        id={tooltipId}
        className="pointer-events-none invisible absolute bottom-full left-0 z-20 mb-2 w-max max-w-56 rounded-md bg-foreground px-2 py-1 text-[11px] font-medium text-background opacity-0 shadow-md transition-opacity group-hover:visible group-hover:opacity-100 group-focus-visible:visible group-focus-visible:opacity-100"
      >
        {hint}
      </span>
    </span>
  );
}
