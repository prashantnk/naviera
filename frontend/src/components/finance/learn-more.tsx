// frontend/src/components/finance/learn-more.tsx
"use client";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useTenant } from "@/components/providers/tenant-provider";
import { ExternalLink, HelpCircle } from "lucide-react";

interface LearnMoreProps {
  /** Heading of the popover (usually the page name). */
  title: string;
  /** Short plain-language rules shown as bullets. */
  points: readonly string[];
}

/**
 * "Learn More" pill used beside the page titles of the finance / support screens
 * (Delhivery One shows a help link in the same place). Opens a popover with the
 * page's rules and, when the workspace configured one in Settings, a link to its
 * Help Center (`tenant.settings.support.help_center_url`).
 */
export function LearnMore({ title, points }: LearnMoreProps) {
  const { tenant } = useTenant();
  const helpCenterUrl = tenant?.settings?.support?.help_center_url?.trim();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 rounded-full border-slate-200 bg-slate-100 px-3 text-xs font-medium text-slate-700 hover:bg-slate-200"
          data-testid="learn-more.trigger"
        >
          <HelpCircle className="h-3.5 w-3.5 text-primary" />
          Learn More
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-2 text-xs">
        <p className="font-bold text-slate-900">{title}</p>
        <ul className="list-disc space-y-1.5 pl-4 leading-relaxed text-slate-600">
          {points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        {helpCenterUrl && (
          <a
            href={helpCenterUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 pt-1 font-semibold text-primary hover:underline"
          >
            Open Help Center
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </PopoverContent>
    </Popover>
  );
}
