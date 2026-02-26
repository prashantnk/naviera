// src/components/blocks/admin-timeline.tsx
import { ActivityType, ShipmentActivityRead } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { Badge } from "@/components/ui/badge";
import { Activity, ArrowRight, Box, ChevronRight, Clock, Eye, EyeOff, FileJson, FileText, Pencil } from "lucide-react";

export function AdminTimeline({ activities }: { activities: ShipmentActivityRead[] }) {
    const { user, isAdmin } = useUser();

    const formatDate = (isoString: string) => {
        return new Date(isoString).toLocaleString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: 'numeric', minute: '2-digit', hour12: true
        });
    };

    const getTypeColor = (type: ActivityType) => {
        switch (type) {
            case ActivityType.STATUS_CHANGE: return "bg-blue-100 text-blue-700 border-blue-200";
            case ActivityType.INFO_UPDATE: return "bg-amber-100 text-amber-700 border-amber-200";
            case ActivityType.EXCEPTION: return "bg-red-100 text-red-700 border-red-200";
            default: return "bg-slate-100 text-slate-700 border-slate-200";
        }
    };

    // Converts JSON into Human-Readable Sentences
    const renderHumanizedDiff = (diff: any) => {
        if (!diff || Object.keys(diff).length === 0) return null;

        return (
            <ul className="mt-3 space-y-2 text-xs text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100">
                {Object.entries(diff).map(([key, value]: [string, any]) => {
                    const cleanKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

                    if (key === 'packages' || key === 'documents') {
                        const added = value.added?.length || 0;
                        const removed = value.removed?.length || 0;
                        const modified = value.modified?.length || 0;
                        const changes = [];

                        if (added) changes.push(`Added ${added}`);
                        if (removed) changes.push(`Removed ${removed}`);
                        if (modified) changes.push(`Modified ${modified}`);

                        return (
                            <li key={key} className="flex items-start gap-2">
                                <Box className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
                                <span><strong>{cleanKey}:</strong> {changes.join(', ')}</span>
                            </li>
                        );
                    }

                    if (value && value.old !== undefined && value.new !== undefined) {
                        return (
                            <li key={key} className="flex items-start gap-2">
                                <Pencil className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
                                <span>
                                    Changed <strong>{cleanKey}</strong> from{' '}
                                    <span className="line-through text-red-400">{String(value.old)}</span>{' '}
                                    <ArrowRight className="inline h-3 w-3 mx-1 text-slate-400" />{' '}
                                    <span className="text-green-600 font-medium">{String(value.new)}</span>
                                </span>
                            </li>
                        );
                    }

                    if (typeof value === 'string') {
                        return (
                            <li key={key} className="flex items-start gap-2">
                                <FileText className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
                                <span><strong>{cleanKey}:</strong> {value}</span>
                            </li>
                        );
                    }

                    return null;
                })}
            </ul>
        );
    };

    return (
        <div className="w-full bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col h-[600px]">            {/* Header */}
            <div className="p-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between shrink-0">
                <h3 className="font-semibold text-slate-900 flex items-center gap-2">
                    <Activity className="h-4 w-4 text-primary" /> Audit Log & History
                </h3>
                <Badge variant="outline" className="bg-white">{activities.length} Events</Badge>
            </div>

            {/* Left-Aligned Timeline Body - Using robust native scrolling! */}
            <div className="flex-1 overflow-y-auto p-6">
                <div className="relative border-l-2 border-slate-200 ml-4 space-y-8 pb-4">

                    {activities.length === 0 && (
                        <div className="pl-8 text-slate-500 italic text-sm">No activity recorded yet.</div>
                    )}

                    {activities.map((activity) => (
                        <div key={activity.id} className="relative pl-8 pr-4">

                            {/* The Center Dot */}
                            <div className="absolute -left-[17px] top-0 flex items-center justify-center w-8 h-8 rounded-full border-4 border-white bg-slate-100 text-slate-500 shadow-sm z-10">
                                <Clock className="h-3.5 w-3.5" />
                            </div>

                            {/* The Content Card */}
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                                <div className="flex items-center gap-3">
                                    <span className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full border ${getTypeColor(activity.activity_type)}`}>
                                        {activity.activity_type.replace("_", " ")}
                                    </span>
                                    <h4 className="font-semibold text-slate-900 text-sm">{activity.summary || "System Update"}</h4>
                                </div>

                                <div className="flex items-center gap-3 text-xs font-medium text-slate-400">
                                    {activity.is_public ? (
                                        <span className="flex items-center text-green-600 bg-green-50 px-2 py-0.5 rounded-md" title="Visible on Public Tracking">
                                            <Eye className="h-3 w-3 mr-1" /> Public
                                        </span>
                                    ) : (
                                        <span className="flex items-center text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md" title="Internal Logistics Only">
                                            <EyeOff className="h-3 w-3 mr-1" /> Internal
                                        </span>
                                    )}
                                    <span className="whitespace-nowrap">{formatDate(activity.timestamp)}</span>
                                </div>
                            </div>

                            {/* Admin Comment */}
                            {activity.comment && (
                                <p className="text-sm text-slate-700 bg-blue-50/50 p-3 rounded-lg border border-blue-100/50 italic mb-2">
                                    "{activity.comment}"
                                </p>
                            )}

                            {/* Translated Human Diff */}
                            {renderHumanizedDiff(activity.diff)}

                            {/* 🔥 NEW: Collapsible Raw JSON Diff */}
                            {isAdmin && activity.diff && Object.keys(activity.diff).length > 0 && (
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