// frontend/src/components/blocks/footer.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Facebook, Instagram, Linkedin, Mail, Package2, Phone, Youtube } from "lucide-react";
import Link from "next/link";

export function Footer() {
    const { tenant, routeTo } = useTenant();
    const contact = tenant?.settings?.contact;
    const brand = tenant?.settings?.brand;

    return (
        <footer className="bg-slate-950 text-slate-300 pt-16 pb-8 border-t-[6px] border-primary">
            <div className="container mx-auto px-4 md:px-6 max-w-7xl">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-12 mb-12 border-b border-slate-800 pb-12">

                    {/* Column 1: Contacts (FIXED STACKED LAYOUT) */}
                    <div className="lg:col-span-1 space-y-6">
                        <Link href={routeTo("/")} className="flex items-center gap-2">
                            {brand?.logo_url ? (
                                <img src={brand.logo_url} alt={tenant?.name} className="h-10 bg-white p-1 rounded object-contain" />
                            ) : (
                                <Package2 className="h-8 w-8 text-primary" />
                            )}
                            <span className="text-2xl font-bold tracking-tight text-white">
                                {tenant?.name || "Naviera"}
                            </span>
                        </Link>

                        <div className="space-y-6 text-sm pt-4">
                            {contact?.phones && contact.phones.length > 0 && (
                                <div className="space-y-3">
                                    <span className="font-bold text-white uppercase tracking-wider text-xs">Phone Support</span>
                                    {contact.phones.map((phone) => (
                                        <a href={`tel:${phone.replace(/[^0-9+]/g, '')}`} key={phone} className="flex items-center gap-3 group w-fit cursor-pointer">
                                            <div className="h-8 w-8 rounded-full bg-slate-800 flex items-center justify-center group-hover:bg-primary transition-colors">
                                                <Phone className="h-3.5 w-3.5 text-white" />
                                            </div>
                                            <span className="font-medium text-slate-300 group-hover:text-white transition-colors">{phone}</span>
                                        </a>
                                    ))}
                                </div>
                            )}

                            {contact?.emails && contact.emails.length > 0 && (
                                <div className="space-y-3 pt-2">
                                    <span className="font-bold text-white uppercase tracking-wider text-xs">Email Support</span>
                                    {contact.emails.map((email) => (
                                        <a href={`mailto:${email}`} key={email} className="flex items-center gap-3 group w-fit cursor-pointer">
                                            <div className="h-8 w-8 rounded-full bg-slate-800 flex items-center justify-center group-hover:bg-primary transition-colors">
                                                <Mail className="h-3.5 w-3.5 text-white" />
                                            </div>
                                            <span className="font-medium text-slate-300 group-hover:text-white transition-colors">{email}</span>
                                        </a>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Column 2: Quick Links */}
                    <div>
                        <h4 className="font-bold text-white mb-6 text-sm uppercase tracking-wider">Company</h4>
                        <ul className="space-y-3 text-sm">
                            <li><Link href={routeTo("/about")} className="hover:text-primary transition-colors flex items-center gap-2">About Us</Link></li>
                            <li><Link href={routeTo("/services")} className="hover:text-primary transition-colors flex items-center gap-2">Our Services</Link></li>
                            <li><Link href={routeTo("/contact")} className="hover:text-primary transition-colors flex items-center gap-2">Contact Us</Link></li>
                        </ul>
                    </div>

                    {/* Column 3: Logistics */}
                    <div>
                        <h4 className="font-bold text-white mb-6 text-sm uppercase tracking-wider">Logistics</h4>
                        <ul className="space-y-3 text-sm">
                            <li><Link href={routeTo("/shipments/new")} className="hover:text-primary transition-colors">Book a Shipment</Link></li>
                            <li><Link href={routeTo("/track")} className="hover:text-primary transition-colors">Track a Package</Link></li>
                            <li><Link href={routeTo("/login")} className="hover:text-primary transition-colors">Customer Portal Login</Link></li>
                        </ul>
                    </div>

                    {/* Column 4: Socials */}
                    <div>
                        <h4 className="font-bold text-white mb-6 text-sm uppercase tracking-wider">Follow Us</h4>
                        <div className="flex items-center gap-4">
                            <Link href={contact?.socials?.facebook || "#"} className="h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center hover:bg-primary hover:text-white transition-all">
                                <Facebook className="h-5 w-5" />
                            </Link>
                            <Link href={contact?.socials?.instagram || "#"} className="h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center hover:bg-primary hover:text-white transition-all">
                                <Instagram className="h-5 w-5" />
                            </Link>
                            <Link href={contact?.socials?.youtube || "#"} className="h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center hover:bg-primary hover:text-white transition-all">
                                <Youtube className="h-5 w-5" />
                            </Link>
                            <Link href={contact?.socials?.linkedin || "#"} className="h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center hover:bg-primary hover:text-white transition-all">
                                <Linkedin className="h-5 w-5" />
                            </Link>
                        </div>
                    </div>
                </div>

                {/* Bottom Legal Bar */}
                <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-slate-500">
                    <p>© {new Date().getFullYear()} {tenant?.name || "Naviera"}. All rights reserved.</p>

                    {/* 🔥 POWERED BY NAVIERA */}
                    <div className="flex items-center gap-2 bg-slate-900 px-4 py-2 rounded-full border border-slate-800">
                        <span>Powered by</span>
                        <div className="flex items-center gap-1.5 font-bold text-slate-300">
                            <Package2 className="h-4 w-4 text-blue-500" /> Naviera
                        </div>
                    </div>
                </div>
            </div>
        </footer>
    );
}