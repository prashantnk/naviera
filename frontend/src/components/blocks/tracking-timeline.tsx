// src/components/blocks/tracking-timeline.tsx
import { PickupStatus, PublicActivityRead, PublicTrackingRead } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, CheckCircle2, Copy, MapPin, Package, Truck } from "lucide-react";

export function TrackingTimeline({ data }: { data: PublicTrackingRead }) {

    // Advanced Dynamic Theming for Timeline Icons
    const getStepStyling = (statusTitle: string) => {
        const s = statusTitle.toLowerCase();
        if (s.includes("delivered") || s.includes("completed")) {
            return { bg: "bg-green-100", text: "text-green-600", Icon: CheckCircle2 };
        }
        if (s.includes("transit") || s.includes("out for delivery")) {
            return { bg: "bg-blue-100", text: "text-blue-600", Icon: Truck };
        }
        if (s.includes("warehouse") || s.includes("facility") || s.includes("picked up")) {
            return { bg: "bg-purple-100", text: "text-purple-600", Icon: MapPin };
        }
        if (s.includes("cancelled") || s.includes("exception") || s.includes("failed")) {
            return { bg: "bg-red-100", text: "text-red-600", Icon: AlertCircle };
        }
        // Default (Booked, Open, Draft)
        return { bg: "bg-slate-100", text: "text-slate-600", Icon: Package };
    };

    const formatDate = (isoString: string) => {
        return new Date(isoString).toLocaleString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
        });
    };

    const formatTime = (isoString: string) => {
        return new Date(isoString).toLocaleString('en-US', {
            hour: 'numeric', minute: '2-digit', hour12: true
        });
    };

    // Determine header badge color
    let badgeVariant: "default" | "secondary" | "destructive" = "secondary";
    if (data.status === PickupStatus.COMPLETED || data.status === PickupStatus.IN_TRANSIT) badgeVariant = "default";
    if (data.status === PickupStatus.CANCELLED) badgeVariant = "destructive";

    return (
        <div className="w-full max-w-2xl mx-auto bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">

            {/* Header Section */}
            <div className="p-6 md:p-8 border-b border-slate-100 flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest flex items-center gap-1.5 mb-2">
                        <MapPin className="h-3.5 w-3.5" /> Tracking ID
                    </p>
                    <div className="flex items-center gap-3">
                        <h2 className="text-2xl md:text-3xl font-extrabold text-slate-900 tracking-tight">{data.tracking_id}</h2>
                        <button className="text-slate-400 hover:text-slate-900 transition-colors" title="Copy ID">
                            <Copy className="h-5 w-5" />
                        </button>
                    </div>
                </div>

                <Badge variant={badgeVariant} className="text-sm px-4 py-1.5 w-fit rounded-full shadow-sm">
                    {data.status.replace("_", " ")}
                </Badge>
            </div>

            {/* Timeline Section */}
            <div className="p-6 md:p-8">
                {/* The connecting vertical line */}
                <div className="relative border-l-2 border-slate-200 ml-4 space-y-10 pb-4">

                    {data.timeline?.length === 0 && (
                        <div className="pl-8 text-slate-500 italic">Tracking details will appear here shortly.</div>
                    )}

                    {data.timeline?.map((event: PublicActivityRead, index: number) => {
                        const style = getStepStyling(event.status_title);
                        const Icon = style.Icon;

                        return (
                            <div key={index} className="relative pl-8 md:pl-10">
                                {/* The Timeline Dot - Perfectly aligned over the border */}
                                <div className={`absolute -left-[17px] top-0 h-8 w-8 rounded-full ring-8 ring-white flex items-center justify-center ${style.bg} ${style.text}`}>
                                    <Icon className="h-4 w-4 stroke-[2.5px]" />
                                </div>

                                {/* The Content */}
                                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-baseline gap-2 pt-1">
                                    <h3 className="text-base font-bold text-slate-900">{event.status_title}</h3>
                                    <div className="flex sm:flex-col gap-2 sm:gap-0 sm:text-right text-sm font-medium text-slate-500">
                                        <span>{formatTime(event.timestamp)}</span>
                                        <span className="text-slate-400 sm:text-xs">{formatDate(event.timestamp)}</span>
                                    </div>
                                </div>

                                {event.message && (
                                    <p className="text-slate-600 mt-2 text-sm max-w-md leading-relaxed">
                                        {event.message}
                                    </p>
                                )}
                            </div>
                        );
                    })}

                </div>
            </div>

            {/* Footer Section */}
            {data.estimated_delivery && (
                <div className="p-6 md:p-8 bg-slate-50/80 border-t border-slate-100 flex justify-between items-center">
                    <span className="text-sm font-medium text-slate-500">Estimated delivery</span>
                    <span className="text-base font-bold text-slate-900">{formatDate(data.estimated_delivery)}</span>
                </div>
            )}
        </div>
    );
}