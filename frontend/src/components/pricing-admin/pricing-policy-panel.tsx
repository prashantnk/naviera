// frontend/src/components/pricing-admin/pricing-policy-panel.tsx
"use client";

/**
 * Settings ▸ Pricing: Delhivery markup, Prime default markup, COD fee and the
 * services customers can book (`GET/PUT /api/v1/pricing/policy`).
 *
 * It saves on its own endpoint, separately from the main settings form. It is
 * rendered inside the settings page's `<form>`, so it never renders a nested
 * `<form>`: buttons are `type="button"` and Enter in an input is swallowed so it
 * cannot submit the outer settings form.
 *
 * Spring analogy: a self-contained view backed by its own `@RestController`.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { IndianRupee, Loader2, RotateCcw, Save, ShieldAlert, Truck } from "lucide-react";
import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScreenGuideBanner, type GuideStep } from "@/components/ui/screen-guide-banner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { InputAdornment } from "@/components/ui/form-extras";
import { Input } from "@/components/ui/input";
import {
  buildQueryCacheKey,
  getCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { extractApiErrorMessage } from "@/lib/utils";

import { NoticeBanner, NoticeTone } from "./notice-banner";
import { MarkupRow } from "./markup-row";
import {
  ALL_SERVICE_OPTIONS,
  fetchPricingPolicy,
  updatePricingPolicy,
  type PricingPolicy,
  type PricingPolicyRead,
  type ServiceOption,
} from "./pricing-admin-api";
import {
  describePolicyChanges,
  formValuesToPolicy,
  hasCompleteCodFee,
  policyToFormValues,
  pricingPolicySchema,
  SERVICE_OPTION_HINTS,
  SERVICE_OPTION_LABELS,
  toEditablePolicy,
  type PolicyChange,
  type PricingPolicyFormValues,
} from "./pricing-policy-form";

const TEST_ID = "pricing-policy";
const LOAD_ERROR_TEXT = "We couldn't load your pricing settings.";
const SAVE_ERROR_TEXT = "Pricing was not saved.";
const SAVED_TEXT = "Pricing saved. New bookings use it from now on; booked shipments keep their price.";
const EMPTY_FORM: PricingPolicyFormValues = policyToFormValues({});

const PRICING_GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "Set Service Markups (% or Flat ₹)",
    description:
      "Add your margin on top of live Delhivery B2C/B2B carrier rates, or set a global Prime markup.",
  },
  {
    title: "Configure COD Fee",
    description:
      "Set minimum ₹ and % of goods value. Customers pay whichever is higher to cover Delhivery's COD charge.",
  },
  {
    title: "Enable Bookable Services",
    description:
      "Switch Delhivery Surface, Express, B2B Cargo, or Logismart Prime on/off for customer rate shopping.",
  },
];

interface PricingPolicyPanelProps {
  /** Tenant slug header for the API calls. */
  tenantSlug: string | null | undefined;
  /** Owner/admin may edit; other staff see the same screen read-only. */
  canEdit: boolean;
}

/**
 * Stops Enter in a text box from submitting the surrounding settings form.
 *
 * @param event - Key event bubbling from any input in the panel.
 */
function _swallowEnter(event: KeyboardEvent<HTMLDivElement>): void {
  if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
    event.preventDefault();
  }
}

/**
 * Renders the pricing policy editor (or a read-only view for non-admin staff).
 *
 * @param props - See `PricingPolicyPanelProps`.
 */
export function PricingPolicyPanel({ tenantSlug, canEdit }: PricingPolicyPanelProps) {
  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "pricing-policy");
  const [saved, setSaved] = useState<PricingPolicyRead | null>(() =>
    getCachedQuery<PricingPolicyRead>(cacheKey)
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [pending, setPending] = useState<PricingPolicy | null>(null);
  const [changes, setChanges] = useState<PolicyChange[]>([]);

  const form = useForm<PricingPolicyFormValues>({
    resolver: zodResolver(pricingPolicySchema),
    defaultValues: saved ? policyToFormValues(saved) : EMPTY_FORM,
    mode: "onChange",
  });

  const [reloadKey, setReloadKey] = useState(0);
  const { reset } = form;

  useEffect(() => {
    if (!tenantSlug) return;
    let cancelled = false;
    const cached = getCachedQuery<PricingPolicyRead>(cacheKey);
    if (cached !== null && reloadKey === 0) {
      setSaved(cached);
      setLoadError(null);
      reset(policyToFormValues(cached));
    }
    fetchPricingPolicy(tenantSlug).then(
      (policy) => {
        setCachedQuery(cacheKey, policy);
        if (cancelled) return;
        setSaved(policy);
        setLoadError(null);
        reset(policyToFormValues(policy));
      },
      (err: unknown) => {
        if (!cancelled && cached === null) {
          setLoadError(extractApiErrorMessage(err, LOAD_ERROR_TEXT));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, cacheKey, reset, reloadKey]);

  /** Re-fetches the policy ("Try again" after a load error). */
  const load = useCallback(() => setReloadKey((key) => key + 1), []);

  const [codMin, codPercent] = useWatch({ control: form.control, name: ["cod_fee_min", "cod_fee_percent"] });
  const enabledOptions = useWatch({ control: form.control, name: "enabled_options" });
  const codComplete = hasCompleteCodFee({ cod_fee_min: codMin, cod_fee_percent: codPercent });
  const isDirty = form.formState.isDirty;

  const handleValid = (values: PricingPolicyFormValues) => {
    if (!saved) return;
    const savedPolicy = toEditablePolicy(saved);
    const next = formValuesToPolicy(values, savedPolicy);
    const diff = describePolicyChanges(savedPolicy, next);
    if (diff.length === 0) {
      toast.info("Nothing to save: pricing is unchanged.");
      return;
    }
    setChanges(diff);
    setPending(next);
  };

  const confirmSave = async () => {
    if (!pending) return;
    setIsSaving(true);
    try {
      const updated = await updatePricingPolicy(pending, tenantSlug);
      setCachedQuery(cacheKey, updated);
      setSaved(updated);
      form.reset(policyToFormValues(updated));
      setPending(null);
      toast.success(SAVED_TEXT);
    } catch (err) {
      toast.error(extractApiErrorMessage(err, SAVE_ERROR_TEXT));
    } finally {
      setIsSaving(false);
    }
  };

  const toggleOption = (option: ServiceOption, checked: boolean) => {
    const current = form.getValues("enabled_options");
    const next = checked ? current.concat(option) : current.filter((o) => o !== option);
    form.setValue(
      "enabled_options",
      ALL_SERVICE_OPTIONS.filter((o) => next.includes(o)),
      { shouldDirty: true, shouldValidate: true },
    );
  };

  if (loadError) {
    return (
      <div data-testid={`${TEST_ID}.load-error`} className="space-y-3">
        <NoticeBanner tone={NoticeTone.WARNING} title={LOAD_ERROR_TEXT}>
          {loadError}
        </NoticeBanner>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RotateCcw className="mr-2 h-4 w-4" />
          Try again
        </Button>
      </div>
    );
  }

  if (!saved) {
    return (
      <div data-testid={`${TEST_ID}.loading`} className="space-y-3 py-6 text-sm text-slate-500">
        <span className="sr-only">Loading pricing settings…</span>
        <div className="h-24 w-full rounded-xl bg-slate-100 animate-pulse" />
        <div className="h-32 w-full rounded-xl bg-slate-100 animate-pulse" />
      </div>
    );
  }

  return (
    <div data-testid={`${TEST_ID}.panel`} className="space-y-6" onKeyDown={_swallowEnter}>
      <ScreenGuideBanner
        guideId="pricing-policy"
        title="How Logismart Pricing & Markups Work (3 Steps)"
        delhiveryEquivalent="Delhivery One: Rate Card + Admin Markup"
        steps={PRICING_GUIDE_STEPS}
        isStaff={true}
      />
      <div className="space-y-3">
        {!canEdit && (
          <NoticeBanner tone={NoticeTone.INFO} title="View only" testId={`${TEST_ID}.read-only`}>
            Only the owner or an admin can change pricing.
          </NoticeBanner>
        )}
        {!saved.delhivery_configured && (
          <NoticeBanner
            tone={NoticeTone.WARNING}
            title="Delhivery price API not connected yet"
            testId={`${TEST_ID}.delhivery-not-configured`}
          >
            Delhivery Surface and Delhivery Express show as &ldquo;price unavailable&rdquo; until the
            Delhivery token is set up on the server.
          </NoticeBanner>
        )}
        {!saved.delhivery_b2b_configured && (
          <NoticeBanner
            tone={NoticeTone.WARNING}
            title="Delhivery B2B price API not connected yet"
            testId={`${TEST_ID}.delhivery-b2b-not-configured`}
          >
            Delhivery B2B Cargo shows as &ldquo;price unavailable&rdquo; until the Delhivery B2B
            (LTL) login is set up on the server.
          </NoticeBanner>
        )}
        {codComplete ? (
          <NoticeBanner tone={NoticeTone.SUCCESS} title="COD is ON" testId={`${TEST_ID}.cod-on`}>
            Customers pay ₹{codMin} or {codPercent}% of the goods value, whichever is higher.
            {isDirty && " (after you save)"}
          </NoticeBanner>
        ) : (
          <NoticeBanner
            tone={NoticeTone.WARNING}
            title="COD is OFF for all customers until you set both values"
            testId={`${TEST_ID}.cod-off`}
          >
            Fill in both the minimum COD fee and the COD percentage below, then save.
          </NoticeBanner>
        )}
      </div>

      <Form {...form}>
        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <IndianRupee className="h-5 w-5 text-primary" />
              Markups
            </CardTitle>
            <CardDescription>
              What you add on top of what the carrier charges you, per service: a percentage of the
              carrier cost, or a fixed ₹ amount per shipment (added to the freight; a return-to-origin
              leg gets the same rule). Prices are always worked out by the server, before GST.
            </CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 space-y-3">
            {ALL_SERVICE_OPTIONS.map((option) => (
              <MarkupRow key={option} option={option} canEdit={canEdit} control={form.control} />
            ))}
          </CardContent>
        </Card>

        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <IndianRupee className="h-5 w-5 text-primary" />
              COD fee
            </CardTitle>
            <CardDescription>
              Customers pay the higher of the minimum or the percentage of the goods value. Set it
              high enough to cover Delhivery&apos;s own COD charge, which you pay. Prime has no COD.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 min-w-0 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="cod_fee_min"
              render={({ field }) => (
                <FormItem className="min-w-0">
                  <FormLabel className="text-xs font-bold">Minimum COD fee</FormLabel>
                  <FormControl>
                    <InputAdornment prefix="₹">
                      <Input
                        {...field}
                        inputMode="decimal"
                        placeholder="Not set"
                        disabled={!canEdit}
                        data-testid={`${TEST_ID}.cod-min`}
                        className="min-w-0 w-full bg-white font-mono"
                      />
                    </InputAdornment>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="cod_fee_percent"
              render={({ field }) => (
                <FormItem className="min-w-0">
                  <FormLabel className="text-xs font-bold">COD percentage of goods value</FormLabel>
                  <FormControl>
                    <InputAdornment suffix="%">
                      <Input
                        {...field}
                        inputMode="decimal"
                        placeholder="Not set"
                        disabled={!canEdit}
                        data-testid={`${TEST_ID}.cod-percent`}
                        className="min-w-0 w-full bg-white font-mono"
                      />
                    </InputAdornment>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Truck className="h-5 w-5 text-primary" />
              Services customers can book
            </CardTitle>
            <CardDescription>
              A switched-off service still shows on the rates screen, greyed out, so customers know
              why they cannot pick it.
            </CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 space-y-3">
            {ALL_SERVICE_OPTIONS.map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 min-w-0"
              >
                <input
                  type="checkbox"
                  checked={enabledOptions.includes(option)}
                  disabled={!canEdit}
                  onChange={(e) => toggleOption(option, e.target.checked)}
                  data-testid={`${TEST_ID}.option.${option}`}
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 accent-primary"
                />
                <span className="min-w-0 text-xs break-words">
                  <span className="block font-bold text-slate-900">{SERVICE_OPTION_LABELS[option]}</span>
                  <span className="text-slate-500">{SERVICE_OPTION_HINTS[option]}</span>
                </span>
              </label>
            ))}
            {enabledOptions.length === 0 && (
              <NoticeBanner
                tone={NoticeTone.WARNING}
                title="No service is switched on"
                testId={`${TEST_ID}.no-options`}
              >
                Customers cannot book anything until you switch at least one service on.
              </NoticeBanner>
            )}
          </CardContent>
        </Card>
      </Form>

      {canEdit ? (
        <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm min-w-0 sm:flex-row sm:items-center sm:justify-between">
          <p className="min-w-0 text-xs text-slate-500 break-words">
            Pricing saves on its own with this button. It does not use the Save Settings bar.
          </p>
          <div className="flex flex-wrap justify-end gap-2.5 min-w-0">
            <Button
              type="button"
              variant="outline"
              disabled={!isDirty || isSaving}
              onClick={() => form.reset(policyToFormValues(saved))}
              data-testid={`${TEST_ID}.discard`}
            >
              Discard
            </Button>
            <Button
              type="button"
              disabled={!isDirty || isSaving}
              onClick={form.handleSubmit(handleValid, () =>
                toast.error("Some pricing values are not valid. Check the highlighted boxes."),
              )}
              className="px-6 font-bold"
              data-testid={`${TEST_ID}.save`}
            >
              {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              Save pricing
            </Button>
          </div>
        </div>
      ) : (
        <p className="flex items-center gap-2 text-xs text-slate-500">
          <ShieldAlert className="h-4 w-4" aria-hidden />
          Ask the owner or an admin if these need to change.
        </p>
      )}

      <Dialog open={pending !== null} onOpenChange={(open) => !open && !isSaving && setPending(null)}>
        <DialogContent className="sm:max-w-md" data-testid={`${TEST_ID}.confirm-dialog`}>
          <DialogHeader>
            <DialogTitle>Confirm pricing changes</DialogTitle>
            <DialogDescription>
              These apply to every quote and booking from now on. Shipments already booked keep their
              price.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            {changes.map((change) => (
              <div
                key={change.label}
                className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
              >
                <span className="font-semibold text-slate-700">{change.label}</span>
                <span className="text-right font-mono">
                  <span className="mr-2 text-slate-400 line-through">{change.before}</span>
                  <span className="font-bold text-primary">{change.after}</span>
                </span>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={isSaving} onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button type="button" disabled={isSaving} onClick={confirmSave} data-testid={`${TEST_ID}.confirm-save`}>
              {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Confirm &amp; save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
