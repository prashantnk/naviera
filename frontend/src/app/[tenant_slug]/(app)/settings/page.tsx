// frontend/src/app/[tenant_slug]/(app)/settings/page.tsx
"use client";

import { TenantsService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { FeaturesBlockContent, HeroBlockContent } from "@/types/tenant";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Building2,
  FileText,
  Globe,
  LayoutTemplate,
  Loader2,
  Paintbrush,
  PhoneCall,
  Plus,
  Save,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

// ----------------------------------------------------------------------
// 1. EXHAUSTIVE ZOD SCHEMA
// ----------------------------------------------------------------------
const settingsSchema = z.object({
  brand: z.object({
    primary_color: z.string().regex(/^#([0-9A-F]{3}){1,2}$/i, "Invalid Hex"),
    secondary_color: z.string().regex(/^#([0-9A-F]{3}){1,2}$/i, "Invalid Hex"),
    // logo_url removed as requested!
  }),
  announcement_bar: z.object({
    is_active: z.boolean(),
    text: z.string().optional(),
  }),
  contact: z.object({
    toll_free: z.string().optional(),
    whatsapp: z.string().optional(),
    address: z.string().optional(),
    phones: z.string().optional(),
    emails: z.string().optional(),
  }),
  socials: z.object({
    facebook: z.string().optional(),
    instagram: z.string().optional(),
    linkedin: z.string().optional(),
    youtube: z.string().optional(),
  }),
  // Extracted from landing_page.blocks array for UI convenience
  hero_block: z.object({
    badge: z.string().optional(),
    title: z.string().optional(),
    subtitle: z.string().optional(),
    ctaText: z.string().optional(),
  }),
  features_block: z.object({
    badge: z.string().optional(),
    headline: z.string().optional(),
    subheadline: z.string().optional(),
  }),
  about_page: z.object({
    headline: z.string().optional(),
    paragraphs: z.string().optional(),
    offersHeadline: z.string().optional(),
    // 🔥 NEW: Dynamic Array for Offers
    offers: z.array(z.object({ title: z.string(), description: z.string() })),
  }),
  services_page: z.object({
    headline: z.string().optional(),
    description: z.string().optional(),
    valueAddHeadline: z.string().optional(),
    valueAddDescription: z.string().optional(),
    valueAdds: z.string().optional(),
    // 🔥 NEW: Dynamic Array for Services
    services: z.array(
      z.object({ title: z.string(), description: z.string(), icon: z.string() })
    ),
  }),
  escalation_matrix: z.array(
    z.object({ level: z.string(), email: z.string().email() })
  ),
});

type SettingsValues = z.infer<typeof settingsSchema>;

export default function SettingsPage() {
  const { tenant } = useTenant();
  const { isAdmin } = useUser();
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Hydrate specific blocks from the DB array
  const heroContent = tenant?.settings?.landing_page?.blocks?.find(
    (b) => b.type === "HERO"
  )?.content as HeroBlockContent;
  const featuresContent = tenant?.settings?.landing_page?.blocks?.find(
    (b) => b.type === "FEATURES"
  )?.content as FeaturesBlockContent;

  const form = useForm<SettingsValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      brand: {
        primary_color: tenant?.settings?.brand?.primary_color || "#0f172a",
        secondary_color: tenant?.settings?.brand?.secondary_color || "#1e293b",
      },
      announcement_bar: {
        is_active: tenant?.settings?.announcement_bar?.is_active || false,
        text: tenant?.settings?.announcement_bar?.text || "",
      },
      contact: {
        toll_free: tenant?.settings?.contact?.toll_free || "",
        whatsapp: tenant?.settings?.contact?.whatsapp || "",
        address: tenant?.settings?.contact?.address || "",
        phones: tenant?.settings?.contact?.phones?.join(", ") || "",
        emails: tenant?.settings?.contact?.emails?.join(", ") || "",
      },
      socials: {
        facebook: tenant?.settings?.contact?.socials?.facebook || "",
        instagram: tenant?.settings?.contact?.socials?.instagram || "",
        linkedin: tenant?.settings?.contact?.socials?.linkedin || "",
        youtube: tenant?.settings?.contact?.socials?.youtube || "",
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
        headline: tenant?.settings?.about_page?.headline || "",
        paragraphs:
          tenant?.settings?.about_page?.paragraphs?.join("\n\n") || "",
        offersHeadline: tenant?.settings?.about_page?.offersHeadline || "",
        offers: tenant?.settings?.about_page?.offers || [], // Hydrate Offers Array
      },
      services_page: {
        headline: tenant?.settings?.services_page?.headline || "",
        description: tenant?.settings?.services_page?.description || "",
        valueAddHeadline:
          tenant?.settings?.services_page?.valueAddHeadline || "",
        valueAddDescription:
          tenant?.settings?.services_page?.valueAddDescription || "",
        valueAdds: tenant?.settings?.services_page?.valueAdds?.join("\n") || "",
        services: tenant?.settings?.services_page?.services || [], // Hydrate Services Array
      },
      escalation_matrix: tenant?.settings?.escalation_matrix || [],
    },
  });

  // FIELD ARRAYS (Dynamic Lists)
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

  const livePrimary = form.watch("brand.primary_color");
  const liveSecondary = form.watch("brand.secondary_color");

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
        <ShieldAlert className="h-16 w-16 text-red-500" />
        <h2 className="text-2xl font-bold text-slate-900">Access Denied</h2>
      </div>
    );
  }

  // ----------------------------------------------------------------------
  // 3. DEHYDRATION & SUBMISSION
  // ----------------------------------------------------------------------
  const onSubmit = async (data: SettingsValues) => {
    setIsSubmitting(true);
    try {
      if (!tenant?.id) throw new Error("Tenant ID missing");

      const toArray = (str?: string, separator = ",") =>
        str
          ? str
              .split(separator)
              .map((s) => s.trim())
              .filter(Boolean)
          : [];

      // 🔥 SAFELY RECONSTRUCT THE BLOCKS ARRAY
      const existingBlocks = tenant?.settings?.landing_page?.blocks || [];
      const updatedBlocks = [...existingBlocks];

      // Replace Hero
      const heroIdx = updatedBlocks.findIndex((b) => b.type === "HERO");
      if (heroIdx > -1)
        updatedBlocks[heroIdx] = {
          ...updatedBlocks[heroIdx],
          content: { ...updatedBlocks[heroIdx].content, ...data.hero_block },
        };
      else updatedBlocks.push({ type: "HERO", content: data.hero_block });

      // Replace Features
      const featIdx = updatedBlocks.findIndex((b) => b.type === "FEATURES");
      if (featIdx > -1)
        updatedBlocks[featIdx] = {
          ...updatedBlocks[featIdx],
          content: {
            ...updatedBlocks[featIdx].content,
            ...data.features_block,
          },
        };
      else
        updatedBlocks.push({ type: "FEATURES", content: data.features_block });

      const updatePayload = {
        settings: {
          brand: data.brand,
          announcement_bar: data.announcement_bar,
          contact: {
            toll_free: data.contact.toll_free,
            whatsapp: data.contact.whatsapp,
            address: data.contact.address,
            phones: toArray(data.contact.phones),
            emails: toArray(data.contact.emails),
            socials: data.socials,
          },
          landing_page: { blocks: updatedBlocks },
          about_page: {
            headline: data.about_page.headline,
            paragraphs: toArray(data.about_page.paragraphs, "\n\n"),
            offersHeadline: data.about_page.offersHeadline,
            offers: data.about_page.offers, // Dehydrate updated array
          },
          services_page: {
            headline: data.services_page.headline,
            description: data.services_page.description,
            valueAddHeadline: data.services_page.valueAddHeadline,
            valueAddDescription: data.services_page.valueAddDescription,
            valueAdds: toArray(data.services_page.valueAdds, "\n"),
            services: data.services_page.services, // Dehydrate updated array
          },
          escalation_matrix: data.escalation_matrix,
        },
      };

      await TenantsService.updateTenant(tenant.id, updatePayload);
      toast.success("Settings saved successfully!");
      setTimeout(() => window.location.reload(), 1000);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } catch (error: any) {
      console.error(error);
      toast.error(error.body?.detail || "Failed to update settings.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-12 animate-in fade-in duration-500">
      <style
        dangerouslySetInnerHTML={{
          __html: `:root { --primary: ${livePrimary}; --secondary: ${liveSecondary}; }`,
        }}
      />

      <div>
        <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
          Platform Settings
        </h1>
        <p className="text-slate-500 mt-1">
          Manage exhaustive white-label configuration.
        </p>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">
          <Tabs defaultValue="brand" className="w-full">
            <TabsList className="bg-slate-100/80 border border-slate-200 w-full justify-start h-auto p-1 flex-wrap overflow-x-auto">
              <TabsTrigger value="brand" className="py-2.5 px-4">
                <Paintbrush className="w-4 h-4 mr-2" /> Brand & Contact
              </TabsTrigger>
              <TabsTrigger value="landing" className="py-2.5 px-4">
                <LayoutTemplate className="w-4 h-4 mr-2" /> Landing Page
              </TabsTrigger>
              <TabsTrigger value="about" className="py-2.5 px-4">
                <FileText className="w-4 h-4 mr-2" /> About Us
              </TabsTrigger>
              <TabsTrigger value="services" className="py-2.5 px-4">
                <FileText className="w-4 h-4 mr-2" /> Services
              </TabsTrigger>
              <TabsTrigger value="escalations" className="py-2.5 px-4">
                <Building2 className="w-4 h-4 mr-2" /> Support Matrix
              </TabsTrigger>
            </TabsList>

            {/* --- TAB: BRAND & CONTACT --- */}
            <TabsContent value="brand" className="mt-6 space-y-6">
              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Theme Colors</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-8">
                  <FormField
                    control={form.control}
                    name="brand.primary_color"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Primary Color (Hex)</FormLabel>
                        <div className="flex gap-3">
                          <FormControl>
                            <Input
                              type="color"
                              {...field}
                              className="w-16 h-10 p-1"
                            />
                          </FormControl>
                          <FormControl>
                            <Input
                              type="text"
                              {...field}
                              className="font-mono uppercase"
                            />
                          </FormControl>
                        </div>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="brand.secondary_color"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Secondary Color (Hex)</FormLabel>
                        <div className="flex gap-3">
                          <FormControl>
                            <Input
                              type="color"
                              {...field}
                              className="w-16 h-10 p-1"
                            />
                          </FormControl>
                          <FormControl>
                            <Input
                              type="text"
                              {...field}
                              className="font-mono uppercase"
                            />
                          </FormControl>
                        </div>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Contact & Socials</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <FormField
                    control={form.control}
                    name="contact.toll_free"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Toll Free</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="contact.whatsapp"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>WhatsApp</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="contact.phones"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Phones (Comma separated)</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="contact.emails"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Emails (Comma separated)</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="contact.address"
                    render={({ field }) => (
                      <FormItem className="md:col-span-2">
                        <FormLabel>Address</FormLabel>
                        <FormControl>
                          <Textarea className="h-20" {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {/* --- TAB: LANDING PAGE --- */}
            <TabsContent value="landing" className="mt-6 space-y-6">
              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Announcement Bar</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="announcement_bar.is_active"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Enable Announcement Bar?</FormLabel>
                        <Select
                          onValueChange={(v) => field.onChange(v === "true")}
                          value={field.value ? "true" : "false"}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="true">Yes, show it</SelectItem>
                            <SelectItem value="false">No, hide it</SelectItem>
                          </SelectContent>
                        </Select>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="announcement_bar.text"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Announcement Text</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Hero Section</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <FormField
                    control={form.control}
                    name="hero_block.badge"
                    render={({ field }) => (
                      <FormItem className="md:col-span-2">
                        <FormLabel>Pill Badge Text</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="hero_block.title"
                    render={({ field }) => (
                      <FormItem className="md:col-span-2">
                        <FormLabel>Main Headline (H1)</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="hero_block.subtitle"
                    render={({ field }) => (
                      <FormItem className="md:col-span-2">
                        <FormLabel>Subtitle</FormLabel>
                        <FormControl>
                          <Textarea {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="hero_block.ctaText"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Button Text</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {/* --- TAB: ABOUT US (With Field Array) --- */}
            <TabsContent value="about" className="mt-6 space-y-6">
              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>About Us Content</CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                  <FormField
                    control={form.control}
                    name="about_page.headline"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Headline</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="about_page.paragraphs"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          Story Paragraphs (Double Enter to split)
                        </FormLabel>
                        <FormControl>
                          <Textarea className="h-32" {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <div className="pt-4 border-t border-slate-100">
                    <FormField
                      control={form.control}
                      name="about_page.offersHeadline"
                      render={({ field }) => (
                        <FormItem className="mb-4">
                          <FormLabel>Offers Section Headline</FormLabel>
                          <FormControl>
                            <Input {...field} />
                          </FormControl>
                        </FormItem>
                      )}
                    />

                    {/* 🔥 DYNAMIC OFFERS ARRAY */}
                    <div className="space-y-4">
                      {offerFields.map((field, index) => (
                        <div
                          key={field.id}
                          className="flex flex-col gap-3 p-4 border border-slate-200 rounded-lg bg-slate-50 relative group"
                        >
                          <Button
                            type="button"
                            variant="destructive"
                            size="icon"
                            className="absolute top-2 right-2 h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
                            onClick={() => removeOffer(index)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                          <FormField
                            control={form.control}
                            name={`about_page.offers.${index}.title`}
                            render={({ field }) => (
                              <FormItem>
                                <FormLabel className="text-xs">
                                  Offer Title
                                </FormLabel>
                                <FormControl>
                                  <Input {...field} className="bg-white" />
                                </FormControl>
                              </FormItem>
                            )}
                          />
                          <FormField
                            control={form.control}
                            name={`about_page.offers.${index}.description`}
                            render={({ field }) => (
                              <FormItem>
                                <FormLabel className="text-xs">
                                  Description
                                </FormLabel>
                                <FormControl>
                                  <Textarea
                                    {...field}
                                    className="bg-white h-16"
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
                        className="w-full border-dashed"
                      >
                        <Plus className="h-4 w-4 mr-2" /> Add Offer
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* --- TAB: SERVICES (With Field Array) --- */}
            <TabsContent value="services" className="mt-6 space-y-6">
              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Services Array</CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* 🔥 DYNAMIC SERVICES ARRAY */}
                  <div className="space-y-4">
                    {serviceFields.map((field, index) => (
                      <div
                        key={field.id}
                        className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 border border-slate-200 rounded-lg bg-slate-50 relative group"
                      >
                        <Button
                          type="button"
                          variant="destructive"
                          size="icon"
                          className="absolute top-2 right-2 h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={() => removeService(index)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                        <FormField
                          control={form.control}
                          name={`services_page.services.${index}.title`}
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel className="text-xs">
                                Service Title
                              </FormLabel>
                              <FormControl>
                                <Input {...field} className="bg-white" />
                              </FormControl>
                            </FormItem>
                          )}
                        />
                        <FormField
                          control={form.control}
                          name={`services_page.services.${index}.icon`}
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel className="text-xs">
                                Lucide Icon Name (e.g. &apos;truck&apos;)
                              </FormLabel>
                              <FormControl>
                                <Input {...field} className="bg-white" />
                              </FormControl>
                            </FormItem>
                          )}
                        />
                        <FormField
                          control={form.control}
                          name={`services_page.services.${index}.description`}
                          render={({ field }) => (
                            <FormItem className="md:col-span-2">
                              <FormLabel className="text-xs">
                                Description
                              </FormLabel>
                              <FormControl>
                                <Textarea
                                  {...field}
                                  className="bg-white h-16"
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
                        appendService({
                          title: "",
                          description: "",
                          icon: "box",
                        })
                      }
                      className="w-full border-dashed"
                    >
                      <Plus className="h-4 w-4 mr-2" /> Add Service
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* --- TAB: ESCALATIONS --- */}
            <TabsContent value="escalations" className="mt-6">
              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Escalation Matrix</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {escalationFields.map((field, index) => (
                    <div
                      key={field.id}
                      className="flex items-end gap-4 p-4 border border-slate-100 rounded-lg bg-slate-50"
                    >
                      <FormField
                        control={form.control}
                        name={`escalation_matrix.${index}.level`}
                        render={({ field }) => (
                          <FormItem className="flex-1">
                            <FormLabel className="text-xs">
                              Level Name
                            </FormLabel>
                            <FormControl>
                              <Input
                                placeholder="Level 1"
                                {...field}
                                className="bg-white"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name={`escalation_matrix.${index}.email`}
                        render={({ field }) => (
                          <FormItem className="flex-1">
                            <FormLabel className="text-xs">Email</FormLabel>
                            <FormControl>
                              <Input
                                placeholder="support@xyz.com"
                                {...field}
                                className="bg-white"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        className="text-red-500 hover:bg-red-50 hover:text-red-700"
                        onClick={() => removeEscalation(index)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => appendEscalation({ level: "", email: "" })}
                    className="w-full border-dashed"
                  >
                    <Plus className="h-4 w-4 mr-2" /> Add Escalation Level
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          <div className="sticky bottom-4 flex justify-end p-4 bg-white/80 backdrop-blur-md border border-slate-200 rounded-xl shadow-lg">
            <Button
              type="submit"
              size="lg"
              disabled={isSubmitting}
              className="font-bold px-8 shadow-sm"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Syncing
                  Config...
                </>
              ) : (
                <>
                  <Save className="mr-2 h-5 w-5" /> Save Global Configuration
                </>
              )}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
