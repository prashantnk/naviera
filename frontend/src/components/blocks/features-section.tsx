// frontend/src/components/blocks/features-section.tsx
"use client";

import { ClientLogo, FeaturesBlockContent } from "@/types/tenant";
import { CheckCircle2, Globe2, MonitorSmartphone, PackageCheck, ShoppingBag } from "lucide-react";

// Map string keys from the DB to actual React components safely
const iconMap: Record<string, React.ElementType> = {
    "monitor": MonitorSmartphone,
    "shopping-bag": ShoppingBag,
    "globe": Globe2,
    "package": PackageCheck,
};

// 🔥 RESTORED: Smart Brand Logo Mapper (Brings back the beautiful typography!)
function TrustedBrandLogo({ brand }: { brand: ClientLogo }) {
    // Handle both old string format and new object format gracefully
    const name = typeof brand === "string" ? brand : brand.name;
    const n = name.toUpperCase();

    if (n === "NESTLE") return <span className="text-2xl font-bold text-blue-800 tracking-tight">Nestle</span>;
    if (n === "ITC LIMITED") return <span className="text-3xl font-black text-red-600 tracking-tighter">ITC Limited</span>;
    if (n === "JOCKEY") return <span className="text-2xl font-extrabold text-slate-900 italic">JOCKEY</span>;
    if (n === "WILLS LIFESTYLE") return <span className="text-2xl font-bold text-slate-800 uppercase tracking-widest">Wills Lifestyle</span>;
    if (n === "MICROMAX") return <span className="text-2xl font-bold text-blue-600">micro<span className="font-light">max</span></span>;
    if (n === "MRF") return <span className="text-3xl font-black text-red-700 italic pr-2">MRF</span>;
    if (n === "ASHOK LEYLAND") return <span className="text-2xl font-bold text-slate-900 uppercase">Ashok Leyland</span>;
    if (n === "HERO") return <span className="text-3xl font-bold text-red-500">Hero</span>;
    if (n === "DR.REDDY'S" || n === "DR.REDDYS") return <span className="text-2xl font-semibold text-blue-700">Dr.Reddy&apos;s</span>;
    if (n === "NIVEA") return <span className="text-2xl font-bold text-blue-900">NIVEA</span>;
    if (n === "BRITANNIA") return <span className="text-2xl font-bold text-green-700">BRITANNIA</span>;

    // Generic Fallback
    const fallbackColor = typeof brand === "object" && brand.color ? brand.color : "inherit";
    return (
        <span className="text-2xl font-bold tracking-tight uppercase" style={{ color: fallbackColor }}>
            {name}
        </span>
    );
}


export function FeaturesSection({ content }: { content: FeaturesBlockContent }) {
    return (
        <section className="py-24 bg-white">
            <div className="container mx-auto px-4 md:px-6 max-w-7xl">

                {/* Section Header */}
                <div className="text-center max-w-3xl mx-auto mb-16 space-y-4">
                    {content.badge && (
                        <h2
                            className="text-sm font-bold tracking-widest uppercase"
                            style={{ color: 'var(--primary)' }}
                        >
                            {content.badge}
                        </h2>
                    )}
                    <h3 className="text-3xl md:text-5xl font-extrabold text-slate-900 tracking-tight">
                        {content.headline}
                    </h3>
                    {content.subheadline && (
                        <p className="text-lg text-slate-600">
                            {content.subheadline}
                        </p>
                    )}
                </div>

                {/* Features Bento Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mb-24">

                    {content.features.map((feature, index) => {
                        const Icon = iconMap[feature.icon] || PackageCheck;

                        // Layout specific styling logic (to match the beautiful bento box UI)
                        const isLargeLight = index === 0;
                        const isSmallBlue = index === 1;
                        const isSmallRed = index === 2;
                        const isLargeDark = index === 3;

                        return (
                            <div
                                key={index}
                                className={`rounded-3xl p-8 md:p-10 border hover:shadow-lg transition-shadow relative overflow-hidden group ${isLargeLight ? 'lg:col-span-2 bg-slate-50 border-slate-100' :
                                    isSmallBlue ? 'bg-slate-50 border-slate-100' :
                                        isSmallRed ? 'border-slate-100' :
                                            'lg:col-span-2 shadow-xl'
                                    }`}
                                style={
                                    isSmallRed ? { backgroundColor: 'color-mix(in srgb, var(--primary) 5%, white)' } :
                                        isLargeDark ? { backgroundColor: 'var(--secondary)' } : {}
                                }
                            >
                                {/* Background Decorative Icon */}
                                <div className={`absolute right-0 top-0 transform translate-x-1/4 -translate-y-1/4 group-hover:scale-110 transition-transform duration-500 ${isLargeDark ? 'opacity-10' : 'opacity-5'}`}>
                                    <Icon className={`w-64 h-64 ${isLargeDark ? 'text-white' : 'text-slate-900'}`} />
                                </div>

                                <div className="relative z-10">
                                    <div className={`h-14 w-14 rounded-2xl flex items-center justify-center mb-6 shadow-sm border ${isLargeDark ? 'bg-white/10 backdrop-blur border-white/20 text-white' : 'bg-white border-slate-200'
                                        }`}>
                                        <Icon className="h-7 w-7" style={!isLargeDark ? { color: 'var(--primary)' } : {}} />
                                    </div>
                                    <h4 className={`text-2xl font-bold mb-3 ${isLargeDark ? 'text-white' : 'text-slate-900'}`}>
                                        {feature.title}
                                    </h4>
                                    <p className={`text-lg max-w-md mb-6 ${isLargeDark ? 'text-slate-300' : 'text-slate-600'}`}>
                                        {feature.description}
                                    </p>

                                    {feature.bullets && (
                                        <ul className={`space-y-2 text-sm font-medium ${isLargeDark ? 'text-slate-300 grid grid-cols-1 sm:grid-cols-2 gap-2 space-y-0' : 'text-slate-700'}`}>
                                            {feature.bullets.map((bullet, i) => (
                                                <li key={i} className="flex items-center gap-2">
                                                    <CheckCircle2 className="h-4 w-4" style={{ color: isLargeDark ? 'white' : 'var(--primary)' }} />
                                                    {bullet}
                                                </li>
                                            ))}
                                        </ul>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>

                {/* REAL LOGISMART CLIENTS LOGO WALL */}
                {content.clientLogos && content.clientLogos.length > 0 && (
                    <div className="border-t border-slate-200 pt-16 mt-16">
                        <div className="text-center mb-10">
                            <h3 className="text-2xl font-bold text-slate-900">{content.clientsHeadline}</h3>
                            <p className="text-slate-500 mt-2">{content.clientsSubheadline}</p>
                        </div>

                        {/* 🔥 RESTORED: Hover effects and dynamic color/typography rendering */}
                        <div className="flex flex-wrap justify-center items-center gap-x-12 gap-y-8 transition-all duration-700">
                            {content.clientLogos.map((logo, index) => (
                                <div key={index} className="hover:scale-105 transition-transform duration-300">
                                    <TrustedBrandLogo brand={logo} />
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </section>
    );
}