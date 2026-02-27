// frontend/src/app/[tenant_slug]/(marketing)/services/page.tsx
import { getTenantBySlug } from "@/lib/api";
import { CheckCircle2, Plane, RefreshCcw, ShoppingCart, Train, Truck, Warehouse } from "lucide-react";

export default async function ServicesPage({ params }: { params: Promise<{ tenant_slug: string }> }) {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);

    const services = [
        {
            title: "Air Cargo",
            icon: <Plane className="h-8 w-8" />,
            description: "Daily air freight consolidation, direct air freight and transit air freight. Flexible according to schedules and carrier choices. Door to Airport & Airport to Door service available.",
        },
        {
            title: "Train Cargo",
            icon: <Train className="h-8 w-8" />,
            description: "Association with all SLR/VPU coaches in all Rajdhani & Express trains. Cost-effective, timely delivery with 24x7 support and a dedicated operations team for Rail connections.",
        },
        {
            title: "Surface Transportation",
            icon: <Truck className="h-8 w-8" />,
            description: "We operate a 'Hybrid' model of owned and hired vehicles. Providing Full Truck Load (FTL) and Part Load (LTL) transportation safely through our network across India.",
        },
        {
            title: "Warehousing",
            icon: <Warehouse className="h-8 w-8" />,
            description: "Customized, state-of-the-art warehousing services. Complete supply chain solutions including inventory management, packaging, labeling, and distribution.",
        },
        {
            title: "E-Commerce Logistics",
            icon: <ShoppingCart className="h-8 w-8" />,
            description: "Specialized for B2B/B2C startups. Includes Cash on Delivery (COD), Prepaid, Same Day Delivery, Next Day Delivery, Open Delivery, and Try n Buy options.",
        },
        {
            title: "Reverse Logistics",
            icon: <RefreshCcw className="h-8 w-8" />,
            description: "Seamless handling of product returns from the end consumer back to the warehouse. Efficient returns reclamation, secondary distribution, and resale processing.",
        }
    ];

    return (
        <div className="bg-slate-50 min-h-screen py-16">
            <div className="container mx-auto px-4 md:px-6 max-w-7xl">

                <div className="text-center max-w-3xl mx-auto mb-16">
                    <h1 className="text-4xl md:text-5xl font-extrabold text-slate-900 tracking-tight mb-6">Our Services</h1>
                    <p className="text-lg text-slate-600">
                        {tenant?.name} is a multi-modal logistics service provider offering an entire range of integrated supply chain management functions.
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mb-16">
                    {services.map((service, index) => (
                        <div key={index} className="bg-white rounded-3xl p-8 border border-slate-100 shadow-sm hover:shadow-xl transition-all duration-300 group">
                            {/* 🔥 FIX: text-primary on parent, group-hover:text-white overrides it smoothly */}
                            <div className="h-16 w-16 bg-primary/10 text-primary rounded-2xl flex items-center justify-center mb-6 group-hover:scale-110 group-hover:bg-primary group-hover:text-white transition-all">
                                {service.icon}
                            </div>
                            <h3 className="text-2xl font-bold text-slate-900 mb-4">{service.title}</h3>
                            <p className="text-slate-600 leading-relaxed">
                                {service.description}
                            </p>
                        </div>
                    ))}
                </div>

                {/* Value Add Section */}
                <div className="bg-slate-900 rounded-3xl p-8 md:p-12 text-white flex flex-col md:flex-row items-center justify-between gap-8">
                    <div className="max-w-2xl">
                        <h3 className="text-3xl font-bold mb-4">Value For Money</h3>
                        <p className="text-slate-400 text-lg">We provide specialized support for your critical cargo needs.</p>
                    </div>
                    <div className="space-y-4">
                        <div className="flex items-center gap-3"><CheckCircle2 className="text-primary h-6 w-6" /> <span className="font-medium">Round the clock pickup & delivery</span></div>
                        <div className="flex items-center gap-3"><CheckCircle2 className="text-primary h-6 w-6" /> <span className="font-medium">Sunday/Holiday support</span></div>
                        <div className="flex items-center gap-3"><CheckCircle2 className="text-primary h-6 w-6" /> <span className="font-medium">Remote location delivery</span></div>
                    </div>
                </div>

            </div>
        </div>
    );
}