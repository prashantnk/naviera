// frontend/src/app/[tenant_slug]/(marketing)/services/page.tsx
import { getTenantBySlug } from "@/lib/api";
import { CheckCircle2, Plane, RefreshCcw, ShoppingCart, Train, Truck, Warehouse, Package } from "lucide-react";

// Safe dynamic icon mapping
const iconMap: Record<string, React.ElementType> = {
    "plane": Plane,
    "train": Train,
    "truck": Truck,
    "warehouse": Warehouse,
    "shopping-cart": ShoppingCart,
    "refresh-ccw": RefreshCcw,
};

export default async function ServicesPage({ params }: { params: Promise<{ tenant_slug: string }> }) {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);
    const config = tenant?.settings?.services_page;

    if (!config) return <div className="py-20 text-center">Services content coming soon...</div>;

    return (
        <div className="bg-slate-50 min-h-screen py-16">
            <div className="container mx-auto px-4 md:px-6 max-w-7xl">

                <div className="text-center max-w-3xl mx-auto mb-16">
                    <h1 className="text-4xl md:text-5xl font-extrabold text-slate-900 tracking-tight mb-6">{config.headline}</h1>
                    <p className="text-lg text-slate-600">{config.description}</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mb-16">
                    {config.services.map((service, index) => {
                        const Icon = iconMap[service.icon] || Package;
                        return (
                            <div key={index} className="bg-white rounded-3xl p-8 border border-slate-100 shadow-sm hover:shadow-xl transition-all duration-300 group">
                                <div className="h-16 w-16 bg-primary/10 text-primary rounded-2xl flex items-center justify-center mb-6 group-hover:scale-110 group-hover:bg-primary group-hover:text-white transition-all">
                                    <Icon className="h-8 w-8" />
                                </div>
                                <h3 className="text-2xl font-bold text-slate-900 mb-4">{service.title}</h3>
                                <p className="text-slate-600 leading-relaxed">{service.description}</p>
                            </div>
                        );
                    })}
                </div>

                {/* Value Add Section */}
                <div className="bg-slate-900 rounded-3xl p-8 md:p-12 text-white flex flex-col md:flex-row items-center justify-between gap-8">
                    <div className="max-w-2xl">
                        <h3 className="text-3xl font-bold mb-4">{config.valueAddHeadline}</h3>
                        <p className="text-slate-400 text-lg">{config.valueAddDescription}</p>
                    </div>
                    <div className="space-y-4">
                        {config.valueAdds.map((add, i) => (
                            <div key={i} className="flex items-center gap-3">
                                <CheckCircle2 className="text-primary h-6 w-6 shrink-0" /> 
                                <span className="font-medium">{add}</span>
                            </div>
                        ))}
                    </div>
                </div>

            </div>
        </div>
    );
}