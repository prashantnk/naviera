// frontend/src/components/blocks/admin-timeline.tsx
import { ActivityType, ShipmentActivityRead } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Activity,
  ArrowRight,
  Box,
  ChevronRight,
  Clock,
  ExternalLink,
  Eye,
  EyeOff,
  FileJson,
  FileText,
  Pencil,
} from "lucide-react";
import Link from "next/link";

export function AdminTimeline({
  activities,
  trackingId,
}: {
  activities: ShipmentActivityRead[];
  trackingId?: string | null;
}) {
  const { isAdmin } = useUser();
  const { routeTo } = useTenant();

  const formatDate = (isoString: string) => {
    return new Date(isoString).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  };

  const getTypeColor = (type: ActivityType) => {
    switch (type) {
      case ActivityType.STATUS_CHANGE:
        return "bg-blue-100 text-blue-700 border-blue-200";
      case ActivityType.INFO_UPDATE:
        return "bg-amber-100 text-amber-700 border-amber-200";
      case ActivityType.EXCEPTION:
        return "bg-red-100 text-red-700 border-red-200";
      default:
        return "bg-slate-100 text-slate-700 border-slate-200";
    }
  };

  const renderHumanizedDiff = (diff: Record<string, unknown> | undefined) => {
    if (!diff || Object.keys(diff).length === 0) return null;

    return (
      <ul className="mt-3 space-y-2 text-xs text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100">
        {Object.entries(diff).map(([key, value]) => {
          const cleanKey = key
            .replace(/_/g, " ")
            .replace(/\b\w/g, (l) => l.toUpperCase());

          if (key === "packages" || key === "documents") {
            const valObj = value as {
              added?: unknown[];
              removed?: unknown[];
              modified?: unknown[];
            } | null | undefined;
            const added = valObj?.added?.length || 0;
            const removed = valObj?.removed?.length || 0;
            const modified = valObj?.modified?.length || 0;
            const changes = [];

            if (added) changes.push(`Added ${added}`);
            if (removed) changes.push(`Removed ${removed}`);
            if (modified) changes.push(`Modified ${modified}`);

            return (
              <li key={key} className="flex items-start gap-2">
                <Box className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
                <span>
                  <strong>{cleanKey}:</strong> {changes.join(", ")}
                </span>
              </li>
            );
          }

          const valOldNew = value as { old?: unknown; new?: unknown } | null | undefined;
          if (valOldNew && valOldNew.old !== undefined && valOldNew.new !== undefined) {
            return (
              <li key={key} className="flex items-start gap-2">
                <Pencil className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
                <span>
                  Changed <strong>{cleanKey}</strong> from{" "}
                  <span className="line-through text-red-400">
                    {String(valOldNew.old)}
                  </span>{" "}
                  <ArrowRight className="inline h-3 w-3 mx-1 text-slate-400" />{" "}
                  <span className="text-green-600 font-medium">
                    {String(valOldNew.new)}
                  </span>
                </span>
              </li>
            );
          }

          if (typeof value === "string") {
            return (
              <li key={key} className="flex items-start gap-2">
                <FileText className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
                <span>
                  <strong>{cleanKey}:</strong> {value}
                </span>
              </li>
            );
          }

          return null;
        })}
      </ul>
    );
  };

  return (
    <div className="w-full bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col h-[600px]">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 bg-slate-50/50 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
        <h3 className="font-semibold text-slate-900 flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" /> Audit Log & History
        </h3>

        <div className="flex items-center gap-2">
          <Badge variant="outline" className="bg-white">
            {activities.length} Events
          </Badge>
          {trackingId && (
            <Button
              size="sm"
              asChild
              // 🔥 FIX: Removed the white/slate overrides so it inherits the Primary brand color natively
              className="h-7 text-xs px-3 font-semibold shadow-sm"
            >
              <Link href={routeTo(`/track/${trackingId}`)} target="_blank">
                Public Tracking Page <ExternalLink className="ml-1.5 h-3 w-3" />
              </Link>
            </Button>
          )}
        </div>
      </div>

      {/* Timeline Body */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="relative border-l-2 border-slate-200 ml-4 space-y-8 pb-4">
          {activities.length === 0 && (
            <div className="pl-8 text-slate-500 italic text-sm">
              No activity recorded yet.
            </div>
          )}

          {activities.map((activity) => (
            <div key={activity.id} className="relative pl-8 pr-4">
              <div className="absolute -left-[17px] top-0 flex items-center justify-center w-8 h-8 rounded-full border-4 border-white bg-slate-100 text-slate-500 shadow-sm z-10">
                <Clock className="h-3.5 w-3.5" />
              </div>

              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-3">
                  <span
                    className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full border ${getTypeColor(
                      activity.activity_type
                    )}`}
                  >
                    {activity.activity_type.replace("_", " ")}
                  </span>
                  <h4 className="font-semibold text-slate-900 text-sm">
                    {activity.summary || "System Update"}
                  </h4>
                </div>

                <div className="flex items-center gap-3 text-xs font-medium text-slate-400">
                  {activity.is_public ? (
                    <span
                      className="flex items-center text-green-600 bg-green-50 px-2 py-0.5 rounded-md"
                      title="Visible on Public Tracking"
                    >
                      <Eye className="h-3 w-3 mr-1" /> Public
                    </span>
                  ) : (
                    <span
                      className="flex items-center text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md"
                      title="Internal Logistics Only"
                    >
                      <EyeOff className="h-3 w-3 mr-1" /> Internal
                    </span>
                  )}
                  <span className="whitespace-nowrap">
                    {formatDate(activity.timestamp)}
                  </span>
                </div>
              </div>

              {activity.comment && (
                <p className="text-sm text-slate-700 bg-blue-50/50 p-3 rounded-lg border border-blue-100/50 italic mb-2">
                  &ldquo;{activity.comment}&rdquo;
                </p>
              )}

              {renderHumanizedDiff(activity.diff as Record<string, unknown> | undefined)}

              {isAdmin &&
                activity.diff &&
                Object.keys(activity.diff).length > 0 && (
                  <div className="mt-3 border-t border-slate-100 pt-3">
                    <details className="group">
                      <summary className="text-xs font-medium text-slate-500 cursor-pointer flex items-center gap-1 hover:text-slate-800 transition-colors select-none list-none [&::-webkit-details-marker]:hidden">
                        <FileJson className="h-3.5 w-3.5" />
                        <span>Developer Data (Raw JSON)</span>
                        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90 ml-auto" />
                      </summary>
                      <div className="mt-3">
                        <pre className="text-[10px] bg-slate-900 text-emerald-400 p-3 rounded-lg overflow-x-auto shadow-inner">
                          {JSON.stringify(activity.diff, null, 2)}
                        </pre>
                      </div>
                    </details>
                  </div>
                )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
