// frontend/src/components/blocks/footer.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { LEGAL_PATHS } from "@/lib/legal";
import { Facebook, Instagram, Linkedin, Mail, Package2, Phone, Youtube, type LucideIcon } from "lucide-react";
import Link from "next/link";

/** Public policy pages linked from every marketing page footer. */
export const FOOTER_LEGAL_LINKS: ReadonlyArray<{ label: string; href: string }> = [
    { label: "Terms of Service", href: LEGAL_PATHS.terms },
    { label: "Privacy Policy", href: LEGAL_PATHS.privacy },
    { label: "Refund & Cancellation", href: LEGAL_PATHS.refund },
    { label: "Prohibited Items", href: LEGAL_PATHS.prohibited },
    { label: "Grievance Officer", href: LEGAL_PATHS.grievance },
];

type SocialKey = "facebook" | "instagram" | "youtube" | "linkedin";

/** Social profiles the footer can show, in display order. */
const SOCIAL_PLATFORMS: ReadonlyArray<{ key: SocialKey; label: string; Icon: LucideIcon }> = [
    { key: "facebook", label: "Facebook", Icon: Facebook },
    { key: "instagram", label: "Instagram", Icon: Instagram },
    { key: "youtube", label: "YouTube", Icon: Youtube },
    { key: "linkedin", label: "LinkedIn", Icon: Linkedin },
];

/**
 * Keeps only the social profiles with a real URL, so the footer never renders
 * placeholder "#" links.
 *
 * @param socials - `settings.contact.socials` from the public tenant config.
 * @returns Label, URL and icon of every configured profile.
 */
export function resolveSocialLinks(
    socials: Partial<Record<SocialKey, string>> | undefined
): Array<{ label: string; url: string; Icon: LucideIcon }> {
    return SOCIAL_PLATFORMS.flatMap(({ key, label, Icon }) => {
        const url = socials?.[key]?.trim();
        return url ? [{ label, url, Icon }] : [];
    });
}

export function Footer() {
    const { tenant, routeTo } = useTenant();
    const contact = tenant?.settings?.contact;
    const socialLinks = resolveSocialLinks(contact?.socials);
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
                            <li><Link href={routeTo("/shipments/new/forward")} className="hover:text-primary transition-colors">Book a Shipment</Link></li>
                            <li><Link href={routeTo("/track")} className="hover:text-primary transition-colors">Track a Package</Link></li>
                            <li><Link href={routeTo("/login")} className="hover:text-primary transition-colors">Customer Portal Login</Link></li>
                        </ul>
                    </div>

                    {/* Column 4: Socials (only the profiles the tenant configured; no dead "#" links) */}
                    {socialLinks.length > 0 && (
                        <div>
                            <h4 className="font-bold text-white mb-6 text-sm uppercase tracking-wider">Follow Us</h4>
                            <div className="flex items-center gap-4" data-testid="footer.socials">
                                {socialLinks.map(({ label, url, Icon }) => (
                                    <a
                                        key={label}
                                        href={url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        aria-label={label}
                                        className="h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center hover:bg-primary hover:text-white transition-all"
                                    >
                                        <Icon className="h-5 w-5" />
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Policy links (C-08): Terms, Privacy, Refunds, Prohibited Items, Grievance */}
                <nav aria-label="Legal" data-testid="footer.legal-links" className="mb-6">
                    <ul className="flex flex-wrap justify-center md:justify-start gap-x-6 gap-y-2 text-xs">
                        {FOOTER_LEGAL_LINKS.map((link) => (
                            <li key={link.href}>
                                <Link href={routeTo(link.href)} className="hover:text-primary transition-colors">
                                    {link.label}
                                </Link>
                            </li>
                        ))}
                    </ul>
                </nav>

                {/* Bottom Legal Bar */}
                <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-slate-500">
                    <div className="flex flex-col md:flex-row items-center gap-2 md:gap-4 text-center md:text-left">
                        <p>© {new Date().getFullYear()} {tenant?.name || "Naviera"}. All rights reserved.</p>
                        {contact?.gstin && (
                            <span className="font-mono bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-slate-400 select-all">
                                GSTIN: {contact.gstin}
                            </span>
                        )}
                    </div>

                    {/* 🔥 POWERED BY NAVIERA */}
                    <div className="flex items-center gap-2 bg-slate-900 px-4 py-2 rounded-full border border-slate-800">
                        <span>Powered by</span>
                        <div className="flex items-center gap-1.5 font-bold text-slate-300">
                            <Package2 className="h-4 w-4 text-primary" /> Naviera
                        </div>
                    </div>
                </div>
            </div>
        </footer>
    );
}