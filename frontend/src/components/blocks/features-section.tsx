// src/components/blocks/features-section.tsx
"use client";

import { CheckCircle2, Globe2, MonitorSmartphone, PackageCheck, ShoppingBag } from "lucide-react";

export function FeaturesSection({ tenantName }: { tenantName: string }) {
    return (
        <section className="py-24 bg-white">
            <div className="container mx-auto px-4 md:px-6 max-w-7xl">

                {/* Section Header */}
                <div className="text-center max-w-3xl mx-auto mb-16 space-y-4">
                    <h2 className="text-sm font-bold tracking-widest text-primary uppercase">Why {tenantName}?</h2>
                    <h3 className="text-3xl md:text-5xl font-extrabold text-slate-900 tracking-tight">
                        Complete Logistics & Courier Solutions
                    </h3>
                    <p className="text-lg text-slate-600">
                        We are an Indian company providing logistics & courier solutions to businesses looking for excellence and innovation. Committed to SERVE.
                    </p>
                </div>

                {/* Features Bento Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mb-24">

                    {/* Feature 1 */}
                    <div className="lg:col-span-2 bg-slate-50 rounded-3xl p-8 md:p-12 border border-slate-100 hover:shadow-lg transition-shadow relative overflow-hidden group">
                        <div className="absolute right-0 top-0 opacity-5 transform translate-x-1/4 -translate-y-1/4 group-hover:scale-110 transition-transform duration-500">
                            <MonitorSmartphone className="w-64 h-64 text-slate-900" />
                        </div>
                        <div className="relative z-10">
                            <div className="h-14 w-14 rounded-2xl bg-white border border-slate-200 flex items-center justify-center mb-6 shadow-sm">
                                <MonitorSmartphone className="h-7 w-7 text-primary" />
                            </div>
                            <h4 className="text-2xl font-bold text-slate-900 mb-3">Fully IT Enabled Setup</h4>
                            <p className="text-slate-600 text-lg max-w-md mb-6">
                                Hands-on information for any cargo booked through us. Manage your entire supply chain seamlessly.
                            </p>
                            <ul className="space-y-2 text-sm font-medium text-slate-700">
                                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-green-500" /> Secured Login & Online Tracking</li>
                                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-green-500" /> Generate Manifests & Download MIS</li>
                                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-green-500" /> Order Status & NDR Reports</li>
                                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-green-500" /> COD Remittance Reports</li>
                            </ul>
                        </div>
                    </div>

                    {/* Feature 2 */}
                    <div className="bg-blue-50 rounded-3xl p-8 md:p-10 border border-blue-100 hover:shadow-lg transition-shadow">
                        <div className="h-14 w-14 rounded-2xl bg-white flex items-center justify-center mb-6 shadow-sm text-blue-600">
                            <ShoppingBag className="h-7 w-7" />
                        </div>
                        <h4 className="text-xl font-bold text-slate-900 mb-3">E-Commerce Ready</h4>
                        <p className="text-slate-600 mb-4">
                            Packages tailored for B2B and B2C startups with specialized capabilities.
                        </p>
                        <ul className="space-y-2 text-sm font-medium text-slate-700">
                            <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-blue-500" /> Cash on Delivery (COD)</li>
                            <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-blue-500" /> Reverse Pickup & Open Delivery</li>
                            <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-blue-500" /> Same & Next Day Delivery</li>
                        </ul>
                    </div>

                    {/* Feature 3 */}
                    <div className="bg-primary/5 rounded-3xl p-8 md:p-10 border border-primary/10 hover:shadow-lg transition-shadow">
                        <div className="h-14 w-14 rounded-2xl bg-white flex items-center justify-center mb-6 shadow-sm text-primary">
                            <Globe2 className="h-7 w-7" />
                        </div>
                        <h4 className="text-xl font-bold text-slate-900 mb-3">Pan India Presence</h4>
                        <p className="text-slate-600">
                            Distance & time are not a barrier for us. Air, Surface, Train, Cargo, Export, and Import covered extensively.
                        </p>
                    </div>

                    {/* Feature 4 */}
                    <div className="lg:col-span-2 bg-slate-900 rounded-3xl p-8 md:p-12 shadow-xl relative overflow-hidden group">
                        <div className="absolute right-0 top-0 opacity-10 transform translate-x-1/4 -translate-y-1/4 group-hover:rotate-12 transition-transform duration-700">
                            <PackageCheck className="w-64 h-64 text-white" />
                        </div>
                        <div className="relative z-10">
                            <div className="h-14 w-14 rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center mb-6 text-white">
                                <PackageCheck className="h-7 w-7" />
                            </div>
                            <h4 className="text-2xl font-bold text-white mb-3">Value For Money</h4>
                            <p className="text-slate-400 text-lg max-w-lg mb-4">
                                Our seamless nature integrates directly with client workflows, making us the intelligent choice for prime customer service.
                            </p>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-slate-300 text-sm">
                                <p>✓ Round the clock pickup & delivery</p>
                                <p>✓ Single account multiple locations</p>
                                <p>✓ Sunday/Holiday support</p>
                                <p>✓ Remote location delivery</p>
                            </div>
                        </div>
                    </div>

                </div>

                {/* 🔥 REAL LOGISMART CLIENTS LOGO WALL */}
                <div className="border-t border-slate-200 pt-16 mt-16">
                    <div className="text-center mb-10">
                        <h3 className="text-2xl font-bold text-slate-900">Trusted by Leading Brands Across Industries</h3>
                        <p className="text-slate-500 mt-2">Apparel, Electronics, Automotive, FMCG & Pharma</p>
                    </div>

                    {/* We use highly stylized text to represent the brands since we don't have their image files */}
                    <div className="flex flex-wrap justify-center items-center gap-x-12 gap-y-8 opacity-60 grayscale hover:grayscale-0 transition-all duration-700">
                        <span className="text-2xl font-bold text-blue-800 tracking-tight">Nestle</span>
                        <span className="text-3xl font-black text-red-600 tracking-tighter">ITC Limited</span>
                        <span className="text-2xl font-extrabold text-slate-900 italic">JOCKEY</span>
                        <span className="text-2xl font-bold text-slate-800 uppercase tracking-widest">Wills Lifestyle</span>
                        <span className="text-2xl font-bold text-blue-600">micro<span className="font-light">max</span></span>
                        <span className="text-3xl font-black text-red-700 italic pr-2">MRF</span>
                        <span className="text-2xl font-bold text-slate-900 uppercase">Ashok Leyland</span>
                        <span className="text-3xl font-bold text-red-500">Hero</span>
                        <span className="text-2xl font-semibold text-blue-700">Dr.Reddy&apos;s</span>
                        <span className="text-2xl font-bold text-blue-900">NIVEA</span>
                        <span className="text-2xl font-bold text-green-700">BRITANNIA</span>
                    </div>
                </div>

            </div>
        </section>
    );
}