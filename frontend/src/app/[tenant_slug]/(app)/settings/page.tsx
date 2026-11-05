// frontend/src/app/[tenant_slug]/(app)/settings/page.tsx
"use client";

import { TenantsService, WalletService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { PricingPolicyPanel } from "@/components/pricing-admin/pricing-policy-panel";
import { useTenant } from "@/components/providers/tenant-provider";
import {
  companyPatchFromValues,
  companyValuesFromSettings,
  storedInvoicePrefix,
} from "@/components/settings/company-profile";
import { IconPicker } from "@/components/settings/icon-picker";
import {
  sectionForErrors,
  SECTION_LABELS as SECTION_TITLES,
  type SettingsSectionId as SectionId,
} from "@/components/settings/settings-sections";
import {
  revalidateTenantSettingsCache,
  SettingsHistoryDialog,
} from "@/components/settings/settings-history-drawer";
import {
  ChipListInput,
  OrderedTextListEditor,
} from "@/components/settings/string-list-editor";
import {
  BRAND_PALETTE_PRESETS,
  isLowContrastWithWhite,
} from "@/components/settings/theme-presets";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { InputAdornment } from "@/components/ui/form-extras";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { normalizeServiceIconKey } from "@/lib/icon-registry";
import {
  buildQueryCacheKey,
  getCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import {
  EscalationLevel,
  FeaturesBlockContent,
  HeroBlockContent,
  PageBlock,
  ServiceItem,
  TenantSettings,
} from "@/types/tenant";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  ExternalLink,
  Globe,
  Headset,
  History,
  IndianRupee,
  Loader2,
  MapPin,
  Package2,
  Paintbrush,
  Plus,
  RotateCcw,
  Save,
  ShieldAlert,
  Trash2,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

const HEADLINE_LIMIT = 120;
const PARAGRAPH_LIMIT = 1000;
const SHORT_TEXT_LIMIT = 255;
const ADDRESS_LIMIT = 500;

const HEX_REGEX = /^#([0-9A-F]{3}){1,2}$/i;
const GSTIN_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const UPI_VPA_REGEX = /^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9.-]{1,63}$/;
const PHONE_REGEX = /^\+?[0-9][0-9 ()-]{5,18}[0-9]$/;
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ESCALATION_LEVEL_OPTIONS = [
  "Level 1 — Customer Support",
  "Level 2 — Operations Lead",
  "Level 3 — Nodal Officer",
  "Level 4 — Management Escalation",
] as const;

type SettingsSectionId = SectionId;

const SETTINGS_SECTIONS: readonly {
  id: SettingsSectionId;
  label: string;
  description: string;
  icon: typeof Building2;
}[] = [
  {
    id: "company",
    label: "Company Profile",
    description: "GSTIN & registered office",
    icon: Building2,
  },
  {
    id: "branding",
    label: "Branding & Theme",
    description: "Brand colours, presets & live preview",
    icon: Paintbrush,
  },
  {
    id: "website",
    label: "Website Content",
    description: "Landing, About & Services pages",
    icon: Globe,
  },
  {
    id: "support",
    label: "Support & Escalation",
    description: "Help Center, phones, emails & matrix",
    icon: Headset,
  },
  {
    id: "wallet",
    label: "Wallet & Payments",
    description: "UPI merchant VPA & Finlock gates",
    icon: Wallet,
  },
  {
    id: "rates",
    label: "Pricing",
    description: "Markups, COD fee & services",
    icon: IndianRupee,
  },
] as const;

const settingsSchema = z.object({
  brand: z.object({
    primary_color: z.string().regex(HEX_REGEX, "Must be a valid hex colour (e.g. #0F172A)"),
    secondary_color: z.string().regex(HEX_REGEX, "Must be a valid hex colour (e.g. #1E293B)"),
  }),
  announcement_bar: z.object({
    is_active: z.boolean(),
    text: z.string().max(SHORT_TEXT_LIMIT).optional(),
  }),
  company: z.object({
    legal_name: z.string().max(SHORT_TEXT_LIMIT),
    gstin: z
      .string()
      .refine((v) => !v.trim() || GSTIN_REGEX.test(v.trim().toUpperCase()), {
        message: "Must be a valid 15-character GSTIN (e.g. 27AAACL9999A1Z2)",
      }),
    pan: z
      .string()
      .refine((v) => !v.trim() || PAN_REGEX.test(v.trim().toUpperCase()), {
        message: "Must be a valid 10-character PAN (e.g. AAECL2138H)",
      }),
    registered_address: z.string().max(ADDRESS_LIMIT),
    contact_email: z
      .string()
      .refine((v) => !v.trim() || EMAIL_REGEX.test(v.trim()), {
        message: "Enter a valid email address",
      }),
    contact_phone: z
      .string()
      .refine((v) => !v.trim() || PHONE_REGEX.test(v.trim()), {
        message: "Enter a valid phone number",
      }),
  }),
  contact: z.object({
    toll_free: z.string().optional(),
    whatsapp: z.string().optional(),
    address: z.string().max(ADDRESS_LIMIT).optional(),
    phones: z.array(z.string()),
    emails: z.array(z.string()),
  }),
  support: z.object({
    help_center_url: z
      .string()
      .max(2048)
      .optional()
      .refine((v) => !v || !v.trim() || v.trim().startsWith("https://"), {
        message: "Help Center URL must start with https://",
      }),
  }),
  socials: z.object({
    facebook: z.string().optional(),
    instagram: z.string().optional(),
    linkedin: z.string().optional(),
    youtube: z.string().optional(),
  }),
  hero_block: z.object({
    badge: z.string().max(HEADLINE_LIMIT).optional(),
    title: z.string().max(HEADLINE_LIMIT).optional(),
    subtitle: z.string().max(PARAGRAPH_LIMIT).optional(),
    ctaText: z.string().max(HEADLINE_LIMIT).optional(),
  }),
  features_block: z.object({
    badge: z.string().max(HEADLINE_LIMIT).optional(),
    headline: z.string().max(HEADLINE_LIMIT).optional(),
    subheadline: z.string().max(PARAGRAPH_LIMIT).optional(),
  }),
  about_page: z.object({
    headline: z.string().max(HEADLINE_LIMIT).optional(),
    paragraphs: z.array(z.string().max(PARAGRAPH_LIMIT)),
    offersHeadline: z.string().max(HEADLINE_LIMIT).optional(),
    offers: z.array(
      z.object({
        title: z.string().max(HEADLINE_LIMIT),
        description: z.string().max(PARAGRAPH_LIMIT),
      }),
    ),
  }),
  services_page: z.object({
    headline: z.string().max(HEADLINE_LIMIT).optional(),
    description: z.string().max(PARAGRAPH_LIMIT).optional(),
    valueAddHeadline: z.string().max(HEADLINE_LIMIT).optional(),
    valueAddDescription: z.string().max(PARAGRAPH_LIMIT).optional(),
    valueAdds: z.array(z.string().max(SHORT_TEXT_LIMIT)),
    services: z.array(
      z.object({
        title: z.string().max(HEADLINE_LIMIT),
        description: z.string().max(PARAGRAPH_LIMIT),
        icon: z.string(),
      }),
    ),
  }),
  escalation_matrix: z.array(
    z.object({
      level: z.string().max(50),
      email: z.string().email("Enter a valid email address"),
      phone: z.string().optional(),
    }),
  ),
  wallet_config: z.object({
    merchant_vpa: z
      .string()
      .refine((v) => !v.trim() || UPI_VPA_REGEX.test(v.trim()), {
        message: "Must be a valid UPI ID (e.g. name@bank)",
      }),
    merchant_name: z.string().max(100),
    min_wallet_balance_b2c: z.number().min(0, "Cannot be negative"),
    min_wallet_balance_b2b: z.number().min(0, "Cannot be negative"),
    strict_finlock: z.boolean(),
  }),
});

type SettingsValues = z.infer<typeof settingsSchema>;

function buildValuesFromSettings(
  rawSettings: TenantSettings | undefined,
  tenantName: string,
): SettingsValues {
  const blocks: PageBlock[] = rawSettings?.landing_page?.blocks || [];
  const heroContent = blocks.find((b) => b.type === "HERO")?.content as
    | HeroBlockContent
    | undefined;
  const featuresContent = blocks.find((b) => b.type === "FEATURES")?.content as
    | FeaturesBlockContent
    | undefined;

  const rawServices: ServiceItem[] = rawSettings?.services_page?.services || [];

  return {
    brand: {
      primary_color: rawSettings?.brand?.primary_color || "#0F172A",
      secondary_color: rawSettings?.brand?.secondary_color || "#1E293B",
    },
    announcement_bar: {
      is_active: Boolean(rawSettings?.announcement_bar?.is_active),
      text: rawSettings?.announcement_bar?.text || "",
    },
    company: companyValuesFromSettings(
      rawSettings as Record<string, unknown> | undefined,
    ),
    contact: {
      toll_free: rawSettings?.contact?.toll_free || "",
      whatsapp: rawSettings?.contact?.whatsapp || "",
      address: rawSettings?.contact?.address || "",
      phones: Array.isArray(rawSettings?.contact?.phones)
        ? rawSettings.contact.phones
        : [],
      emails: Array.isArray(rawSettings?.contact?.emails)
        ? rawSettings.contact.emails
        : [],
    },
    support: {
      help_center_url: rawSettings?.support?.help_center_url || "",
    },
    socials: {
      facebook: rawSettings?.contact?.socials?.facebook || "",
      instagram: rawSettings?.contact?.socials?.instagram || "",
      linkedin: rawSettings?.contact?.socials?.linkedin || "",
      youtube: rawSettings?.contact?.socials?.youtube || "",
    },
    hero_block: {
      badge: heroContent?.badge || "",
      title: heroContent?.title || "",
      subtitle: heroContent?.subtitle || "",
      ctaText: heroContent?.ctaText || "",
    },
    features_block: {
      badge: featuresContent?.badge || "",
      headline: featuresContent?.headline || "",
      subheadline: featuresContent?.subheadline || "",
    },
    about_page: {
      headline: rawSettings?.about_page?.headline || "",
      paragraphs: Array.isArray(rawSettings?.about_page?.paragraphs)
        ? rawSettings.about_page.paragraphs
        : [],
      offersHeadline: rawSettings?.about_page?.offersHeadline || "",
      offers: Array.isArray(rawSettings?.about_page?.offers)
        ? rawSettings.about_page.offers
        : [],
    },
    services_page: {
      headline: rawSettings?.services_page?.headline || "",
      description: rawSettings?.services_page?.description || "",
      valueAddHeadline: rawSettings?.services_page?.valueAddHeadline || "",
      valueAddDescription:
        rawSettings?.services_page?.valueAddDescription || "",
      valueAdds: Array.isArray(rawSettings?.services_page?.valueAdds)
        ? rawSettings.services_page.valueAdds
        : [],
      services: rawServices.map((svc) => ({
        title: svc?.title || "",
        description: svc?.description || "",
        icon: normalizeServiceIconKey(svc?.icon) || "truck",
      })),
    },
    escalation_matrix: Array.isArray(rawSettings?.escalation_matrix)
      ? rawSettings.escalation_matrix.map((row: EscalationLevel) => ({
          level: row?.level || "",
          email: row?.email || "",
          phone: row?.phone || "",
        }))
      : [],
    wallet_config: {
      merchant_vpa: rawSettings?.wallet_config?.merchant_vpa || "",
      merchant_name:
        rawSettings?.wallet_config?.merchant_name ||
        tenantName ||
        "Logismart Logistics",
      min_wallet_balance_b2c: Number(
        rawSettings?.wallet_config?.min_wallet_balance_b2c ?? 0,
      ),
      min_wallet_balance_b2b: Number(
        rawSettings?.wallet_config?.min_wallet_balance_b2b ?? 500,
      ),
      strict_finlock: Boolean(
        rawSettings?.wallet_config?.strict_finlock ?? false,
      ),
    },
  };
}

export default function SettingsPage() {
  const { tenant, tenantSlug, routeTo } = useTenant();
  const { capabilities } = useUser();
  const isAdmin = capabilities.canManageSettings;
  const settingsCacheKey = buildQueryCacheKey(
    tenantSlug,
    "session",
    "tenant-settings-admin",
  );
  const cachedAdminSettings = getCachedQuery<{
    mergedSettings: TenantSettings;
    tenantName: string;
  }>(settingsCacheKey);

  const [activeSection, setActiveSection] =
    useState<SettingsSectionId>("company");
  const { pending: isSubmitting, run: runSave } = useSingleFlight();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [invoicePrefix, setInvoicePrefix] = useState<string | null>(() =>
    cachedAdminSettings
      ? storedInvoicePrefix(
          cachedAdminSettings.mergedSettings as Record<string, unknown>,
        )
      : null,
  );
  const [settingsHydrated, setSettingsHydrated] = useState<boolean>(
    () => cachedAdminSettings !== null,
  );
  const [settingsHydrateError, setSettingsHydrateError] = useState(false);

  const [lastSavedValues, setLastSavedValues] = useState<SettingsValues>(() =>
    cachedAdminSettings
      ? buildValuesFromSettings(
          cachedAdminSettings.mergedSettings,
          cachedAdminSettings.tenantName,
        )
      : buildValuesFromSettings(tenant?.settings, tenant?.name || "Naviera"),
  );

  const form = useForm<SettingsValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: lastSavedValues,
    mode: "onChange",
  });

  const {
    fields: offerFields,
    append: appendOffer,
    remove: removeOffer,
  } = useFieldArray({ control: form.control, name: "about_page.offers" });
  const {
    fields: serviceFields,
    append: appendService,
    remove: removeService,
  } = useFieldArray({ control: form.control, name: "services_page.services" });
  const {
    fields: escalationFields,
    append: appendEscalation,
    remove: removeEscalation,
  } = useFieldArray({ control: form.control, name: "escalation_matrix" });

  const refreshFromBackend = useCallback(async () => {
    // Full settings are Owner/Admin only (403 otherwise): don't even ask for other roles.
    if (!tenantSlug || !isAdmin) return;
    try {
      // Full settings come from the admin-only endpoint; the public tenant
      // payload (useTenant / /tenants/config) only carries allow-listed keys.
      const freshTenant = await TenantsService.getCurrentTenantSettings(tenantSlug);
      const freshSettings = (freshTenant.settings || {}) as TenantSettings;
      const rawWallet = freshSettings.wallet_config;
      const walletOverview = rawWallet?.merchant_vpa
        ? null
        : await WalletService.getWalletOverview(tenantSlug).catch(() => null);
      const mergedSettings: TenantSettings = Object.assign(
        {},
        freshSettings,
        {
          wallet_config: Object.assign(
            {},
            walletOverview?.wallet_config || {},
            rawWallet || {},
          ),
        },
      );
      const hydrated = buildValuesFromSettings(
        mergedSettings,
        freshTenant.name,
      );
      setCachedQuery(settingsCacheKey, {
        mergedSettings,
        tenantName: freshTenant.name,
      });
      setInvoicePrefix(
        storedInvoicePrefix(mergedSettings as Record<string, unknown>),
      );
      setLastSavedValues(hydrated);
      form.reset(hydrated);
      setSettingsHydrated(true);
      setSettingsHydrateError(false);
    } catch {
      if (!getCachedQuery(settingsCacheKey)) {
        setSettingsHydrateError(true);
      }
    }
  }, [tenantSlug, isAdmin, form, settingsCacheKey]);

  useEffect(() => {
    refreshFromBackend();
  }, [refreshFromBackend]);

  const isDirty = form.formState.isDirty;

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!isDirty) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  const livePrimary = form.watch("brand.primary_color");
  const liveSecondary = form.watch("brand.secondary_color");

  const lowPrimaryContrast = useMemo(
    () => isLowContrastWithWhite(livePrimary || "#0F172A"),
    [livePrimary],
  );

  const executeSave = async (data: SettingsValues) => {
    if (!settingsHydrated) {
      toast.error("Please wait for current settings to finish loading before saving.");
      return;
    }
    await runSave(async () => {
      try {
        const existingBlocks = tenant?.settings?.landing_page?.blocks || [];
        const updatedBlocks = existingBlocks.slice();

        const heroIdx = updatedBlocks.findIndex((b) => b.type === "HERO");
        if (heroIdx > -1) {
          updatedBlocks[heroIdx] = Object.assign({}, updatedBlocks[heroIdx], {
            content: Object.assign(
              {},
              updatedBlocks[heroIdx].content,
              data.hero_block,
            ),
          });
        } else {
          updatedBlocks.push({ type: "HERO", content: data.hero_block });
        }

        const featIdx = updatedBlocks.findIndex((b) => b.type === "FEATURES");
        if (featIdx > -1) {
          updatedBlocks[featIdx] = Object.assign({}, updatedBlocks[featIdx], {
            content: Object.assign(
              {},
              updatedBlocks[featIdx].content,
              data.features_block,
            ),
          });
        } else {
          updatedBlocks.push({
            type: "FEATURES",
            content: data.features_block,
          });
        }

        const companyPatch = companyPatchFromValues(data.company);
        // Legacy GSTIN copies stay equal to company.gstin so every backend fallback agrees.
        const cleanGstin = companyPatch.gstin;

        const settingsPayload = {
          brand: {
            primary_color: data.brand.primary_color,
            secondary_color: data.brand.secondary_color,
          },
          announcement_bar: {
            is_active: data.announcement_bar.is_active,
            text: data.announcement_bar.text || "",
          },
          company: companyPatch,
          contact: {
            toll_free: data.contact.toll_free?.trim() || null,
            whatsapp: data.contact.whatsapp?.trim() || null,
            address: data.contact.address?.trim() || null,
            phones: data.contact.phones.map((p) => p.trim()).filter(Boolean),
            emails: data.contact.emails.map((m) => m.trim()).filter(Boolean),
            gstin: cleanGstin,
            socials: {
              facebook: data.socials.facebook?.trim() || null,
              instagram: data.socials.instagram?.trim() || null,
              linkedin: data.socials.linkedin?.trim() || null,
              youtube: data.socials.youtube?.trim() || null,
            },
          },
          support: {
            help_center_url: data.support.help_center_url?.trim() || null,
          },
          landing_page: { blocks: updatedBlocks },
          about_page: {
            headline: data.about_page.headline || "",
            paragraphs: data.about_page.paragraphs
              .map((p) => p.trim())
              .filter(Boolean),
            offersHeadline: data.about_page.offersHeadline || "",
            offers: data.about_page.offers,
          },
          services_page: {
            headline: data.services_page.headline || "",
            description: data.services_page.description || "",
            valueAddHeadline: data.services_page.valueAddHeadline || "",
            valueAddDescription: data.services_page.valueAddDescription || "",
            valueAdds: data.services_page.valueAdds
              .map((v) => v.trim())
              .filter(Boolean),
            services: data.services_page.services.map((s) => ({
              title: s.title,
              description: s.description,
              icon: normalizeServiceIconKey(s.icon) || "truck",
            })),
          },
          escalation_matrix: data.escalation_matrix.map((row) => ({
            level: row.level,
            email: row.email.trim(),
            phone: row.phone?.trim() || null,
          })),
          wallet_config: {
            // Blank clears the UPI ID: wallet recharge then shows "UPI not configured".
            merchant_vpa: data.wallet_config.merchant_vpa.trim() || null,
            merchant_name: data.wallet_config.merchant_name.trim(),
            min_wallet_balance_b2c: data.wallet_config.min_wallet_balance_b2c,
            min_wallet_balance_b2b: data.wallet_config.min_wallet_balance_b2b,
            strict_finlock: data.wallet_config.strict_finlock,
            gstin: cleanGstin,
          },
          gstin: cleanGstin,
        };

        await TenantsService.updateCurrentTenantSettings(
          settingsPayload,
          tenantSlug,
        );

        await revalidateTenantSettingsCache(tenantSlug);

        window.dispatchEvent(new CustomEvent("wallet-updated"));
        setLastSavedValues(data);
        form.reset(data);
        toast.success(
          "Platform settings saved and backed up to version history.",
        );
      } catch (err) {
        toast.error(
          extractApiErrorMessage(err, "Failed to save platform settings."),
        );
      }
    });
  };

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
        <ShieldAlert className="h-16 w-16 text-rose-500" />
        <h2 className="text-2xl font-bold text-slate-900">Access Denied</h2>
        <p className="text-sm text-slate-500 max-w-md">
          Only workspace administrators and owners can modify platform settings.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-28 px-4 md:px-6 animate-in fade-in duration-300">
      <style
        dangerouslySetInnerHTML={{
          __html: `:root { --primary: ${livePrimary}; --secondary: ${liveSecondary}; }`,
        }}
      />

      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-slate-900 tracking-tight">
            Platform Settings
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Configure your brand, public website, support channels, Unified Wallet, and pricing rules in one safe place.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button variant="outline" size="sm" asChild className="bg-white">
            <Link
              href={routeTo("/address-book")}
              prefetch={true}
              data-testid="settings.addresses-link"
            >
              <MapPin className="mr-2 h-4 w-4 text-primary" />
              Saved Addresses
            </Link>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setHistoryOpen(true)}
            className="bg-white"
          >
            <History className="mr-2 h-4 w-4 text-primary" />
            Version History
          </Button>
          <Button variant="outline" size="sm" asChild className="bg-white">
            <Link href={routeTo("/")} prefetch={false} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" />
              View Public Site
            </Link>
          </Button>
        </div>
      </div>

      {/* Mobile horizontal section pills */}
      <div className="flex gap-2 overflow-x-auto pb-2 md:hidden">
        {SETTINGS_SECTIONS.map((sec) => {
          const Icon = sec.icon;
          const active = activeSection === sec.id;
          return (
            <button
              key={sec.id}
              type="button"
              onClick={() => setActiveSection(sec.id)}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-2 text-xs font-bold transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground shadow-sm"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              <span>{sec.label}</span>
            </button>
          );
        })}
      </div>

      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(executeSave, (errors) => {
            const section = sectionForErrors(Object.keys(errors));
            if (section) setActiveSection(section);
            toast.error(
              section
                ? `Some settings are not valid. Fix the highlighted fields in ${SECTION_TITLES[section]}.`
                : "Some settings have validation errors. Check highlighted fields.",
            );
          })}
          className="grid grid-cols-1 gap-6 md:grid-cols-12"
        >
          {/* Left sub-menu (Desktop) */}
          <aside className="hidden min-w-0 md:col-span-4 lg:col-span-3 md:block">
            <nav
              aria-label="Settings sections"
              className="sticky top-20 space-y-1.5 rounded-2xl border border-slate-200 bg-white p-2.5 shadow-sm"
            >
              {SETTINGS_SECTIONS.map((sec) => {
                const Icon = sec.icon;
                const active = activeSection === sec.id;
                return (
                  <button
                    key={sec.id}
                    type="button"
                    onClick={() => setActiveSection(sec.id)}
                    className={cn(
                      "flex w-full items-start gap-3 rounded-xl px-3.5 py-3 text-left transition-all",
                      active
                        ? "bg-primary/10 text-primary ring-1 ring-primary/20"
                        : "text-slate-700 hover:bg-slate-50",
                    )}
                  >
                    <span
                      className={cn(
                        "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                        active
                          ? "bg-primary text-primary-foreground"
                          : "bg-slate-100 text-slate-600",
                      )}
                    >
                      <Icon className="h-4 w-4" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-bold">
                        {sec.label}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">
                        {sec.description}
                      </span>
                    </span>
                  </button>
                );
              })}
            </nav>
          </aside>

          {/* Main Section Panel */}
          <div className="min-w-0 space-y-6 md:col-span-8 lg:col-span-9">
            {/* 1. COMPANY PROFILE */}
            {activeSection === "company" && (
              <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Building2 className="h-5 w-5 text-primary" />
                    Company Profile
                  </CardTitle>
                  <CardDescription>
                    Logismart&apos;s legal and GST identity. It is printed as the supplier on every GST invoice, credit / debit note and wallet receipt issued from now on (documents already issued never change).
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="min-w-0 space-y-1.5">
                      <label className="text-xs font-bold text-slate-700">
                        Workspace Name
                      </label>
                      <Input
                        value={tenant?.name || "Logismart"}
                        disabled
                        className="min-w-0 w-full bg-slate-100 font-semibold text-slate-700"
                      />
                      <p className="text-[11px] text-slate-500">
                        Workspace slug:{" "}
                        <span className="font-mono font-semibold">
                          {tenantSlug}
                        </span>
                      </p>
                    </div>

                    <FormField
                      control={form.control}
                      name="company.legal_name"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Legal Name (as on GST certificate)
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              maxLength={SHORT_TEXT_LIMIT}
                              placeholder="e.g. LOGISMART PRIVATE LIMITED"
                              className="min-w-0 w-full bg-white"
                              data-testid="settings.company.legal-name"
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="company.gstin"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            GSTIN (15 characters)
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              maxLength={15}
                              placeholder="e.g. 27AAACL9999A1Z2"
                              className="min-w-0 w-full bg-white font-mono uppercase"
                              data-testid="settings.company.gstin"
                            />
                          </FormControl>
                          <FormDescription className="text-[11px]">
                            Its first two digits set your GST state (CGST + SGST vs IGST).
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="company.pan"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            PAN (10 characters)
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              maxLength={10}
                              placeholder="e.g. AAECL2138H"
                              className="min-w-0 w-full bg-white font-mono uppercase"
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="company.contact_email"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Billing Email
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              type="email"
                              placeholder="accounts@logismart.in"
                              className="min-w-0 w-full bg-white"
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="company.contact_phone"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Billing Phone
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              placeholder="+91 98765 43210"
                              className="min-w-0 w-full bg-white"
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  <FormField
                    control={form.control}
                    name="company.registered_address"
                    render={({ field }) => (
                      <FormItem className="min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Registered Office Address (printed on GST documents)
                          </FormLabel>
                          <span className="text-[11px] font-mono text-slate-400">
                            {(field.value || "").length} / {ADDRESS_LIMIT}
                          </span>
                        </div>
                        <FormControl>
                          <Textarea
                            {...field}
                            maxLength={ADDRESS_LIMIT}
                            placeholder="Plot / Building, Street, City, State & PIN"
                            className="min-w-0 w-full bg-white h-20"
                            data-testid="settings.company.address"
                          />
                        </FormControl>
                        <FormDescription className="text-[11px]">
                          The public address on your Contact page is set under Support &amp; Escalation.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-xs text-slate-600">
                    <span className="font-bold text-slate-800">GST document prefix: </span>
                    {invoicePrefix ? (
                      <span className="font-mono font-semibold" data-testid="settings.company.invoice-prefix">
                        {invoicePrefix}
                      </span>
                    ) : (
                      <span data-testid="settings.company.invoice-prefix">not set (derived from the workspace slug)</span>
                    )}
                    . It is locked so your invoice series stays continuous within the financial year; contact the platform team to change it before a new financial year.
                  </div>
                </CardContent>
              </Card>
            )}

            {/* 2. BRANDING & THEME */}
            {activeSection === "branding" && (
              <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <CardTitle className="flex items-center gap-2">
                      <Paintbrush className="h-5 w-5 text-primary" />
                      Branding & Runtime Theme
                    </CardTitle>
                    <CardDescription>
                      Pick a curated logistics colour palette or customize hex codes with real-time contrast checks.
                    </CardDescription>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={() => {
                      form.setValue("brand.primary_color", "#0F172A", {
                        shouldDirty: true,
                      });
                      form.setValue("brand.secondary_color", "#1E293B", {
                        shouldDirty: true,
                      });
                    }}
                  >
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                    Reset Theme
                  </Button>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div>
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500">
                      Quick Brand Palette Presets
                    </label>
                    <div className="mt-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                      {BRAND_PALETTE_PRESETS.map((preset) => {
                        const selected =
                          livePrimary?.toUpperCase() ===
                            preset.primary.toUpperCase() &&
                          liveSecondary?.toUpperCase() ===
                            preset.secondary.toUpperCase();
                        return (
                          <button
                            key={preset.id}
                            type="button"
                            onClick={() => {
                              form.setValue(
                                "brand.primary_color",
                                preset.primary,
                                { shouldDirty: true },
                              );
                              form.setValue(
                                "brand.secondary_color",
                                preset.secondary,
                                { shouldDirty: true },
                              );
                            }}
                            className={cn(
                              "flex min-w-0 items-center gap-3 rounded-xl border p-3 text-left transition-all hover:border-primary/40",
                              selected
                                ? "border-primary bg-primary/5 ring-1 ring-primary"
                                : "border-slate-200 bg-white",
                            )}
                          >
                            <span className="flex shrink-0 -space-x-1.5">
                              <span
                                className="h-7 w-7 rounded-full border-2 border-white shadow-xs"
                                style={{ backgroundColor: preset.primary }}
                              />
                              <span
                                className="h-7 w-7 rounded-full border-2 border-white shadow-xs"
                                style={{ backgroundColor: preset.secondary }}
                              />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-xs font-bold text-slate-900">
                                {preset.name}
                              </span>
                              <span className="block truncate text-[11px] text-slate-500">
                                {preset.description}
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                    <FormField
                      control={form.control}
                      name="brand.primary_color"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Primary Brand Colour (Buttons & Highlights)
                          </FormLabel>
                          <div className="flex min-w-0 gap-3">
                            <FormControl>
                              <Input
                                type="color"
                                {...field}
                                className="h-10 w-16 shrink-0 cursor-pointer p-1"
                              />
                            </FormControl>
                            <FormControl>
                              <Input
                                type="text"
                                {...field}
                                className="min-w-0 flex-1 bg-white font-mono uppercase"
                              />
                            </FormControl>
                          </div>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="brand.secondary_color"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Secondary Brand Colour (Dark Banners & Accents)
                          </FormLabel>
                          <div className="flex min-w-0 gap-3">
                            <FormControl>
                              <Input
                                type="color"
                                {...field}
                                className="h-10 w-16 shrink-0 cursor-pointer p-1"
                              />
                            </FormControl>
                            <FormControl>
                              <Input
                                type="text"
                                {...field}
                                className="min-w-0 flex-1 bg-white font-mono uppercase"
                              />
                            </FormControl>
                          </div>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  {lowPrimaryContrast && (
                    <div
                      role="alert"
                      className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-xs text-amber-900"
                    >
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                      <div>
                        <span className="font-bold">
                          Low contrast warning:
                        </span>{" "}
                        This primary colour is very bright, so white button labels may be difficult for users to read. Consider choosing a darker shade.
                      </div>
                    </div>
                  )}

                  {/* Live Theme Preview */}
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                      Live Component Preview
                    </span>
                    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
                      <div className="flex items-center gap-2.5">
                        {tenant?.settings?.brand?.logo_url ? (
                          <img
                            src={tenant.settings.brand.logo_url}
                            alt="Logo preview"
                            className="h-8 object-contain"
                          />
                        ) : (
                          <>
                            <Package2 className="h-6 w-6 text-primary" />
                            <span className="text-lg font-extrabold text-slate-900">
                              {tenant?.name || "Logismart"}
                            </span>
                          </>
                        )}
                        <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-bold text-primary">
                          Active Theme
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button type="button" size="sm">
                          Primary CTA Button
                        </Button>
                        <span
                          className="rounded-lg px-3 py-1.5 text-xs font-bold text-white"
                          style={{ backgroundColor: liveSecondary }}
                        >
                          Secondary Accent
                        </span>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* 3. WEBSITE CONTENT */}
            {activeSection === "website" && (
              <div className="min-w-0 space-y-6">
                {/* Announcement Bar & Hero */}
                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                  <CardHeader>
                    <CardTitle>Landing Page: Announcement & Hero</CardTitle>
                    <CardDescription>
                      Top announcement banner and primary hero section on{" "}
                      <span className="font-mono">/{tenantSlug}</span>.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                      <FormField
                        control={form.control}
                        name="announcement_bar.is_active"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Announcement Bar
                            </FormLabel>
                            <Select
                              onValueChange={(v) =>
                                field.onChange(v === "true")
                              }
                              value={field.value ? "true" : "false"}
                            >
                              <FormControl>
                                <SelectTrigger className="min-w-0 w-full bg-white">
                                  <SelectValue />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                <SelectItem value="true">
                                  Visible on website
                                </SelectItem>
                                <SelectItem value="false">Hidden</SelectItem>
                              </SelectContent>
                            </Select>
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="announcement_bar.text"
                        render={({ field }) => (
                          <FormItem className="min-w-0 md:col-span-2">
                            <div className="flex items-center justify-between gap-2">
                              <FormLabel className="text-xs font-bold">
                                Banner Message
                              </FormLabel>
                              <span className="text-[11px] font-mono text-slate-400">
                                {(field.value || "").length} / {SHORT_TEXT_LIMIT}
                              </span>
                            </div>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={SHORT_TEXT_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    <div className="grid grid-cols-1 gap-4 border-t border-slate-100 pt-4 md:grid-cols-2">
                      <FormField
                        control={form.control}
                        name="hero_block.badge"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Hero Pill Badge
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={HEADLINE_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="hero_block.ctaText"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Hero CTA Button Label
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={HEADLINE_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="hero_block.title"
                        render={({ field }) => (
                          <FormItem className="min-w-0 md:col-span-2">
                            <div className="flex items-center justify-between gap-2">
                              <FormLabel className="text-xs font-bold">
                                Hero Main Headline (H1)
                              </FormLabel>
                              <span className="text-[11px] font-mono text-slate-400">
                                {(field.value || "").length} / {HEADLINE_LIMIT}
                              </span>
                            </div>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={HEADLINE_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="hero_block.subtitle"
                        render={({ field }) => (
                          <FormItem className="min-w-0 md:col-span-2">
                            <div className="flex items-center justify-between gap-2">
                              <FormLabel className="text-xs font-bold">
                                Hero Subtitle
                              </FormLabel>
                              <span className="text-[11px] font-mono text-slate-400">
                                {(field.value || "").length} / {PARAGRAPH_LIMIT}
                              </span>
                            </div>
                            <FormControl>
                              <Textarea
                                {...field}
                                value={field.value || ""}
                                maxLength={PARAGRAPH_LIMIT}
                                className="min-w-0 w-full bg-white h-20"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* About Us Page */}
                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                  <CardHeader>
                    <CardTitle>About Us Page</CardTitle>
                    <CardDescription>
                      Story paragraphs and key offerings displayed on{" "}
                      <span className="font-mono">/{tenantSlug}/about</span>.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    <FormField
                      control={form.control}
                      name="about_page.headline"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold">
                            About Us Headline
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              value={field.value || ""}
                              maxLength={HEADLINE_LIMIT}
                              className="min-w-0 w-full bg-white"
                            />
                          </FormControl>
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="about_page.paragraphs"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold">
                            Company Story Paragraphs
                          </FormLabel>
                          <FormDescription className="text-xs">
                            Each card below is rendered as a separate paragraph on your About page.
                          </FormDescription>
                          <OrderedTextListEditor
                            items={field.value || []}
                            onChange={field.onChange}
                            addButtonLabel="Add Story Paragraph"
                            itemLabel="Paragraph"
                            placeholder="Write a paragraph about your company network, fleet, or mission"
                            multiline
                            maxLength={PARAGRAPH_LIMIT}
                          />
                        </FormItem>
                      )}
                    />

                    <div className="border-t border-slate-100 pt-4 space-y-4">
                      <FormField
                        control={form.control}
                        name="about_page.offersHeadline"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              What We Offer Headline
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={HEADLINE_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />

                      <div className="space-y-3">
                        {offerFields.map((item, index) => (
                          <div
                            key={item.id}
                            className="flex min-w-0 flex-col gap-3 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 p-4"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-xs font-bold text-slate-600">
                                Offer Card #{index + 1}
                              </span>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-rose-600 hover:bg-rose-50"
                                onClick={() => removeOffer(index)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                            <FormField
                              control={form.control}
                              name={`about_page.offers.${index}.title`}
                              render={({ field }) => (
                                <FormItem className="min-w-0">
                                  <FormLabel className="text-xs">
                                    Title
                                  </FormLabel>
                                  <FormControl>
                                    <Input {...field} className="min-w-0 w-full bg-white" />
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                            <FormField
                              control={form.control}
                              name={`about_page.offers.${index}.description`}
                              render={({ field }) => (
                                <FormItem className="min-w-0">
                                  <FormLabel className="text-xs">
                                    Description
                                  </FormLabel>
                                  <FormControl>
                                    <Textarea
                                      {...field}
                                      className="min-w-0 w-full bg-white h-16"
                                    />
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                          </div>
                        ))}
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() =>
                            appendOffer({ title: "", description: "" })
                          }
                          className="w-full border-dashed bg-white"
                        >
                          <Plus className="mr-2 h-4 w-4" /> Add Offer Card
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Services Page (with Visual IconPicker) */}
                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                  <CardHeader>
                    <CardTitle>Services Page & Visual Icon Gallery</CardTitle>
                    <CardDescription>
                      Configure the service cards and value-adds displayed on{" "}
                      <span className="font-mono">/{tenantSlug}/services</span>. Click any icon button to pick from the verified logistics icon gallery.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <FormField
                        control={form.control}
                        name="services_page.headline"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Services Headline
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={HEADLINE_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="services_page.description"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Services Subtitle
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                maxLength={PARAGRAPH_LIMIT}
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                    </div>

                    <div className="space-y-4">
                      <label className="text-xs font-bold uppercase tracking-wider text-slate-500">
                        Service Cards ({serviceFields.length})
                      </label>
                      {serviceFields.map((item, index) => (
                        <div
                          key={item.id}
                          className="grid min-w-0 grid-cols-1 gap-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-12"
                        >
                          <div className="min-w-0 md:col-span-5">
                            <FormField
                              control={form.control}
                              name={`services_page.services.${index}.title`}
                              render={({ field }) => (
                                <FormItem className="min-w-0">
                                  <FormLabel className="text-xs font-bold">
                                    Service Title
                                  </FormLabel>
                                  <FormControl>
                                    <Input
                                      {...field}
                                      maxLength={HEADLINE_LIMIT}
                                      className="min-w-0 w-full bg-white"
                                    />
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                          </div>
                          <div className="min-w-0 md:col-span-6">
                            <FormField
                              control={form.control}
                              name={`services_page.services.${index}.icon`}
                              render={({ field }) => (
                                <FormItem className="min-w-0">
                                  <FormLabel className="text-xs font-bold">
                                    Service Icon (Visual Picker)
                                  </FormLabel>
                                  <FormControl>
                                    <IconPicker
                                      value={field.value}
                                      onChange={(nextKey) =>
                                        field.onChange(nextKey)
                                      }
                                    />
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                          </div>
                          <div className="flex items-end justify-end md:col-span-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-10 w-10 text-rose-600 hover:bg-rose-50"
                              onClick={() => removeService(index)}
                              aria-label={`Remove service ${index + 1}`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                          <div className="min-w-0 md:col-span-12">
                            <FormField
                              control={form.control}
                              name={`services_page.services.${index}.description`}
                              render={({ field }) => (
                                <FormItem className="min-w-0">
                                  <FormLabel className="text-xs font-bold">
                                    Description
                                  </FormLabel>
                                  <FormControl>
                                    <Textarea
                                      {...field}
                                      maxLength={PARAGRAPH_LIMIT}
                                      className="min-w-0 w-full bg-white h-16"
                                    />
                                  </FormControl>
                                </FormItem>
                              )}
                            />
                          </div>
                        </div>
                      ))}

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          appendService({
                            title: "",
                            description: "",
                            icon: "truck",
                          })
                        }
                        className="w-full border-dashed bg-white"
                      >
                        <Plus className="mr-2 h-4 w-4" /> Add Service Card
                      </Button>
                    </div>

                    <div className="border-t border-slate-100 pt-4 space-y-4">
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        <FormField
                          control={form.control}
                          name="services_page.valueAddHeadline"
                          render={({ field }) => (
                            <FormItem className="min-w-0">
                              <FormLabel className="text-xs font-bold">
                                Value-Add Section Headline
                              </FormLabel>
                              <FormControl>
                                <Input
                                  {...field}
                                  value={field.value || ""}
                                  className="min-w-0 w-full bg-white"
                                />
                              </FormControl>
                            </FormItem>
                          )}
                        />
                        <FormField
                          control={form.control}
                          name="services_page.valueAddDescription"
                          render={({ field }) => (
                            <FormItem className="min-w-0">
                              <FormLabel className="text-xs font-bold">
                                Value-Add Subtitle
                              </FormLabel>
                              <FormControl>
                                <Input
                                  {...field}
                                  value={field.value || ""}
                                  className="min-w-0 w-full bg-white"
                                />
                              </FormControl>
                            </FormItem>
                          )}
                        />
                      </div>

                      <FormField
                        control={form.control}
                        name="services_page.valueAdds"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Value-Add Bullet Points
                            </FormLabel>
                            <OrderedTextListEditor
                              items={field.value || []}
                              onChange={field.onChange}
                              addButtonLabel="Add Value-Add Bullet"
                              itemLabel="Bullet"
                              placeholder="e.g. Real-time GPS tracking and automated SMS alerts"
                              maxLength={SHORT_TEXT_LIMIT}
                            />
                          </FormItem>
                        )}
                      />
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* 4. SUPPORT & ESCALATION */}
            {activeSection === "support" && (
              <div className="min-w-0 space-y-6">
                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Headset className="h-5 w-5 text-primary" />
                      Help Center & Customer Support Channels
                    </CardTitle>
                    <CardDescription>
                      Configure your Help Center URL (linked from the merchant dashboard Resources card) and validated phone/email chips.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <FormField
                      control={form.control}
                      name="support.help_center_url"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Help Center / Knowledge Base URL (https://)
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              value={field.value || ""}
                              placeholder="https://help.logismart.in (leave blank to link to your Contact Us page)"
                              className="min-w-0 w-full bg-white font-mono text-xs"
                            />
                          </FormControl>
                          <FormDescription className="text-[11px]">
                            Used by the &ldquo;Help Center / Support &amp; Contacts&rdquo; link in the B2C and B2B dashboard right rail.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <FormField
                        control={form.control}
                        name="contact.toll_free"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Primary Helpline / Toll-Free
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                placeholder="+91 1800 123 4567"
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="contact.whatsapp"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              WhatsApp Support Number
                            </FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                value={field.value || ""}
                                placeholder="+91 98765 43210"
                                className="min-w-0 w-full bg-white"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    <FormField
                      control={form.control}
                      name="contact.address"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <FormLabel className="text-xs font-bold">
                              Office Address (Contact page &amp; footer)
                            </FormLabel>
                            <span className="text-[11px] font-mono text-slate-400">
                              {(field.value || "").length} / {ADDRESS_LIMIT}
                            </span>
                          </div>
                          <FormControl>
                            <Textarea
                              {...field}
                              value={field.value || ""}
                              maxLength={ADDRESS_LIMIT}
                              placeholder="Where customers can reach you"
                              className="min-w-0 w-full bg-white h-20"
                            />
                          </FormControl>
                          <FormDescription className="text-[11px]">
                            The address printed on GST documents is set under Company Profile.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                      <FormField
                        control={form.control}
                        name="contact.phones"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Support Phone Numbers
                            </FormLabel>
                            <ChipListInput
                              values={field.value || []}
                              onChange={field.onChange}
                              placeholder="Type phone (e.g. +91 9876543210) & press Enter"
                              addLabel="Add Phone"
                              validateItem={(val) =>
                                PHONE_REGEX.test(val)
                                  ? null
                                  : "Enter a valid phone number (7–18 digits)."
                              }
                            />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="contact.emails"
                        render={({ field }) => (
                          <FormItem className="min-w-0">
                            <FormLabel className="text-xs font-bold">
                              Support Email Addresses
                            </FormLabel>
                            <ChipListInput
                              values={field.value || []}
                              onChange={field.onChange}
                              placeholder="Type email (e.g. care@logismart.in) & press Enter"
                              addLabel="Add Email"
                              validateItem={(val) =>
                                EMAIL_REGEX.test(val)
                                  ? null
                                  : "Enter a valid email address."
                              }
                            />
                          </FormItem>
                        )}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Escalation Matrix */}
                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                  <CardHeader>
                    <CardTitle>Escalation Matrix</CardTitle>
                    <CardDescription>
                      Published on your Contact page so enterprise shippers know whom to contact at each escalation tier.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {escalationFields.map((item, index) => (
                      <div
                        key={item.id}
                        className="grid min-w-0 grid-cols-1 gap-3 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-12"
                      >
                        <div className="min-w-0 sm:col-span-4">
                          <FormField
                            control={form.control}
                            name={`escalation_matrix.${index}.level`}
                            render={({ field }) => (
                              <FormItem className="min-w-0">
                                <FormLabel className="text-xs font-bold">
                                  Escalation Tier
                                </FormLabel>
                                <Select
                                  value={field.value}
                                  onValueChange={field.onChange}
                                >
                                  <FormControl>
                                    <SelectTrigger className="min-w-0 w-full bg-white">
                                      <SelectValue placeholder="Choose tier" />
                                    </SelectTrigger>
                                  </FormControl>
                                  <SelectContent>
                                    {ESCALATION_LEVEL_OPTIONS.map((opt) => (
                                      <SelectItem key={opt} value={opt}>
                                        {opt}
                                      </SelectItem>
                                    ))}
                                    {field.value &&
                                      !(
                                        ESCALATION_LEVEL_OPTIONS as readonly string[]
                                      ).includes(field.value) && (
                                        <SelectItem value={field.value}>
                                          {field.value}
                                        </SelectItem>
                                      )}
                                  </SelectContent>
                                </Select>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        </div>
                        <div className="min-w-0 sm:col-span-4">
                          <FormField
                            control={form.control}
                            name={`escalation_matrix.${index}.email`}
                            render={({ field }) => (
                              <FormItem className="min-w-0">
                                <FormLabel className="text-xs font-bold">
                                  Escalation Email
                                </FormLabel>
                                <FormControl>
                                  <Input
                                    {...field}
                                    placeholder="nodal@logismart.in"
                                    className="min-w-0 w-full bg-white"
                                  />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        </div>
                        <div className="min-w-0 sm:col-span-3">
                          <FormField
                            control={form.control}
                            name={`escalation_matrix.${index}.phone`}
                            render={({ field }) => (
                              <FormItem className="min-w-0">
                                <FormLabel className="text-xs font-bold">
                                  Direct Phone (Optional)
                                </FormLabel>
                                <FormControl>
                                  <Input
                                    {...field}
                                    value={field.value || ""}
                                    placeholder="+91 98765 00000"
                                    className="min-w-0 w-full bg-white"
                                  />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        </div>
                        <div className="flex items-end justify-end sm:col-span-1">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-10 w-10 text-rose-600 hover:bg-rose-50"
                            onClick={() => removeEscalation(index)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    ))}
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() =>
                        appendEscalation({
                          level: "Level 1 — Customer Support",
                          email: "",
                          phone: "",
                        })
                      }
                      className="w-full border-dashed bg-white"
                    >
                      <Plus className="mr-2 h-4 w-4" /> Add Escalation Tier
                    </Button>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* 5. WALLET & PAYMENTS */}
            {activeSection === "wallet" && (
              <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Wallet className="h-5 w-5 text-primary" />
                    Unified Wallet & NPCI UPI Configuration
                  </CardTitle>
                  <CardDescription>
                    Configure the zero-fee UPI QR payee details and minimum balance (Finlock) gates for B2C and B2B bookings. Saved together with all other settings via the bottom bar.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <FormField
                      control={form.control}
                      name="wallet_config.merchant_vpa"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold">
                            Merchant UPI VPA (Payee Address)
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              placeholder="merchant@okaxis"
                              className="min-w-0 w-full bg-white font-mono text-sm"
                            />
                          </FormControl>
                          <FormDescription className="text-[11px]">
                            Encoded into the dynamic NPCI UPI QR code during merchant wallet recharges.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="wallet_config.merchant_name"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold">
                            Merchant Payee Display Name
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              placeholder="Logismart Logistics"
                              className="min-w-0 w-full bg-white"
                            />
                          </FormControl>
                          <FormDescription className="text-[11px]">
                            Shown in the customer&apos;s UPI app (GPay, PhonePe, Paytm) when scanning.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="wallet_config.min_wallet_balance_b2c"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold">
                            Minimum B2C Express Wallet Balance
                          </FormLabel>
                          <FormControl>
                            <InputAdornment prefix="₹">
                              <Input
                                type="number"
                                min={0}
                                step="50"
                                value={field.value}
                                onChange={(e) =>
                                  field.onChange(Number(e.target.value) || 0)
                                }
                                className="min-w-0 w-full bg-white pl-7 font-mono"
                              />
                            </InputAdornment>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="wallet_config.min_wallet_balance_b2b"
                      render={({ field }) => (
                        <FormItem className="min-w-0">
                          <FormLabel className="text-xs font-bold">
                            Minimum B2B Cargo Finlock Balance
                          </FormLabel>
                          <FormControl>
                            <InputAdornment prefix="₹">
                              <Input
                                type="number"
                                min={0}
                                step="100"
                                value={field.value}
                                onChange={(e) =>
                                  field.onChange(Number(e.target.value) || 0)
                                }
                                className="min-w-0 w-full bg-white pl-7 font-mono"
                              />
                            </InputAdornment>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <FormField
                      control={form.control}
                      name="wallet_config.strict_finlock"
                      render={({ field }) => (
                        <label className="flex cursor-pointer items-start gap-3">
                          <input
                            type="checkbox"
                            checked={field.value}
                            onChange={(e) => field.onChange(e.target.checked)}
                            className="mt-0.5 h-4 w-4 rounded border-slate-300"
                          />
                          <span className="text-xs">
                            <span className="block font-bold text-slate-900">
                              Enforce Strict Finlock Gate on Prepaid Bookings
                            </span>
                            <span className="text-slate-500">
                              When enabled, merchants cannot book prepaid shipments or acknowledge hold charges if their wallet balance is below the required minimum.
                            </span>
                          </span>
                        </label>
                      )}
                    />
                  </div>
                </CardContent>
              </Card>
            )}

            {/* 6. PRICING (Delhivery markup, Prime default markup, COD fee, services) */}
            {activeSection === "rates" && (
              <div className="min-w-0 space-y-6">
                <PricingPolicyPanel tenantSlug={tenantSlug} canEdit={isAdmin} />
                <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <IndianRupee className="h-5 w-5 text-primary" />
                      Logismart Prime lanes
                    </CardTitle>
                    <CardDescription>
                      Transporter rates per route for B2B cargo: edit a lane, switch transporters, or import a CSV.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Button type="button" variant="outline" asChild className="bg-white">
                      <Link href={routeTo("/settings/prime-lanes")} prefetch={true} data-testid="pricing-policy.prime-lanes-link">
                        Open Prime lanes
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>

          {/* ONE Unified Sticky Bottom Save Bar (hidden on Pricing, which saves on its own button) */}
          {activeSection !== "rates" && (
          <div className="md:col-span-12 min-w-0 sticky bottom-4 z-30 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-lg backdrop-blur-md sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-2.5 text-xs">
              {!settingsHydrated ? (
                settingsHydrateError ? (
                  <span className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50 px-3 py-1 font-semibold text-red-800">
                    Couldn&apos;t load full settings.
                    <button
                      type="button"
                      onClick={() => void refreshFromBackend()}
                      className="underline font-bold"
                    >
                      Retry
                    </button>
                  </span>
                ) : (
                  <span
                    data-testid="settings.hydrating"
                    className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 font-semibold text-slate-600"
                  >
                    <span className="h-2.5 w-2.5 rounded-full bg-primary animate-pulse" />
                    Loading workspace settings…
                  </span>
                )
              ) : isDirty ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 font-bold text-amber-800">
                  <span className="h-2 w-2 rounded-full bg-amber-500" />
                  Unsaved changes across settings
                </span>
              ) : (
                <span
                  data-testid="settings.synced"
                  className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 font-semibold text-emerald-800"
                >
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                  All settings saved &amp; synced
                </span>
              )}
            </div>

            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2.5">
              <Button
                type="button"
                variant="outline"
                disabled={!settingsHydrated || !isDirty || isSubmitting}
                onClick={() => form.reset(lastSavedValues)}
              >
                Discard Changes
              </Button>
              <Button
                type="submit"
                disabled={!settingsHydrated || !isDirty || isSubmitting}
                className="font-bold px-4 sm:px-6 shadow-sm"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving Settings
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    Save Settings
                  </>
                )}
              </Button>
            </div>
          </div>
          )}
        </form>
      </Form>

      {/* Version History Drawer / Modal */}
      <SettingsHistoryDialog
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        tenantSlug={tenantSlug}
        onRestored={refreshFromBackend}
      />
    </div>
  );
}
