// frontend/src/components/booking/quote-step.tsx
"use client";

/**
 * Step 2 of every booking wizard (B2C forward/reverse, B2B forward): the service
 * option cards from `POST /api/v1/quotes`, the cash-flow summary and the price
 * breakup of the selected card, then "Book".
 *
 * Every number on this screen is read from the quote response (Zero Frontend Math);
 * the component only formats and arranges them.
 */
import { Button } from "@/components/ui/button";
import { formatInr, formatKg } from "@/components/shipments/shipment-money";
import { SERVICE_OPTION_OPTIONS, getOptionMeta } from "@/lib/form-options";
import { cn } from "@/lib/utils";
import { format, isValid, parseISO } from "date-fns";
import { AlertTriangle, ArrowLeft, Check, Clock, Loader2, Receipt, Scale, Truck, Warehouse } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ServiceOption, type QuoteOption, type QuoteResponse } from "./booking-api";

/** Placeholder cards shown while quotes load. */
const SKELETON_CARD_COUNT = 2;

/** Minimal address shape shown in the journey summary (saved or new address). */
export interface RouteAddress {
  name?: string | null;
  city?: string | null;
  state?: string | null;
  pincode?: string | null;
}

export interface QuoteStepProps {
  quote: QuoteResponse | null;
  isLoading: boolean;
  selectedOption: ServiceOption | null;
  onSelect: (option: ServiceOption) => void;
  onBack: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  /** Whether the user asked for Cash on Delivery on step 1. */
  isCod: boolean;
  pickup?: RouteAddress | null;
  delivery?: RouteAddress | null;
  /** Whether B2B Door Delivery (true) or Godown Self-Pickup (false) is active. */
  doorDelivery?: boolean;
  /** When provided (B2B Step 2), renders the live Door vs Godown toggle and re-quotes on change. */
  onDoorDeliveryChange?: (doorDelivery: boolean) => void;
}

/**
 * Builds the stable test id of an option card, e.g. `booking.quote.card-delhivery-surface`.
 *
 * @param option - Service option value.
 * @returns The `data-testid` value.
 */
export function optionCardTestId(option: ServiceOption): string {
  return `booking.quote.card-${option.toLowerCase().replace(/_/g, "-")}`;
}

/**
 * Finds the selected card in a quote response.
 *
 * @param quote - Quote response (or null while loading).
 * @param selected - Selected option value.
 * @returns The matching card, or null.
 */
export function findSelectedOption(
  quote: QuoteResponse | null,
  selected: ServiceOption | null,
): QuoteOption | null {
  if (!quote || !selected) return null;
  return quote.options.find((option) => option.service_option === selected && option.serviceable) ?? null;
}

/**
 * Picks the card to pre-select after a (re)quote: keep the user's choice if it is
 * still bookable, otherwise the first bookable card.
 *
 * @param quote - Fresh quote response.
 * @param previous - Previously selected option, if any.
 * @returns The option to select, or null when nothing is bookable.
 */
export function defaultSelection(
  quote: QuoteResponse,
  previous: ServiceOption | null,
): ServiceOption | null {
  if (findSelectedOption(quote, previous)) return previous;
  return quote.options.find((option) => option.serviceable)?.service_option ?? null;
}

/**
 * Whether "Book" must stay disabled for reasons the user can fix on step 1.
 *
 * @param quote - Quote response.
 * @param isCod - Whether COD was requested.
 * @returns True when COD was requested but is not available.
 */
export function isCodBlocked(quote: QuoteResponse | null, isCod: boolean): boolean {
  return Boolean(quote && isCod && !quote.cod_available);
}

export function QuoteStep({
  quote,
  isLoading,
  selectedOption,
  onSelect,
  onBack,
  onSubmit,
  isSubmitting,
  isCod,
  pickup,
  delivery,
  doorDelivery,
  onDoorDeliveryChange,
}: QuoteStepProps) {
  const [weightConfirmed, setWeightConfirmed] = useState(false);
  const active = findSelectedOption(quote, selectedOption);
  const codBlocked = isCodBlocked(quote, isCod);
  const needsWeightConfirm = Boolean(quote?.heavy_weight_warning) && !weightConfirmed;
  const canBook = Boolean(active) && !codBlocked && !needsWeightConfirm && !isSubmitting;

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {onDoorDeliveryChange && (
        <DeliveryModeToggleBar
          doorDelivery={Boolean(doorDelivery)}
          isLoading={isLoading}
          onChange={onDoorDeliveryChange}
        />
      )}
      {quote && codBlocked && <CodUnavailableAlert reason={quote.cod_unavailable_reason} onBack={onBack} />}
      {quote?.heavy_weight_warning && (
        <HeavyWeightConfirm
          thresholdKg={quote.heavy_weight_threshold_kg}
          checked={weightConfirmed}
          onChange={setWeightConfirmed}
        />
      )}

      {active && <CashFlowSummary option={active} isCod={isCod} pickup={pickup} delivery={delivery} />}

      <div className="space-y-4 pt-2">
        <div className="border-b border-slate-100 pb-2.5">
          <h3 className="text-base font-extrabold text-slate-950 tracking-tight flex items-center gap-2.5">
            <Receipt className="h-4.5 w-4.5 text-primary shrink-0" />
            <span>Choose a service</span>
          </h3>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {isLoading || !quote
            ? Array.from({ length: SKELETON_CARD_COUNT }).map((_, idx) => <SkeletonCard key={idx} />)
            : quote.options.map((option) => (
                <ServiceOptionCard
                  key={option.service_option}
                  option={option}
                  isSelected={active?.service_option === option.service_option}
                  onSelect={onSelect}
                  doorDelivery={doorDelivery}
                />
              ))}
        </div>
        {!isLoading && quote && quote.options.every((option) => !option.serviceable) && (
          <p className="text-xs text-slate-600" data-testid="booking.quote.none-available">
            No service can take this shipment right now. Check the pincodes and box details, or try again in a few minutes.
          </p>
        )}
      </div>

      {active && <PriceBreakup option={active} />}

      <div className="border-t border-slate-100 pt-6 flex items-center justify-between">
        <Button
          variant="ghost"
          type="button"
          onClick={onBack}
          disabled={isSubmitting}
          className="cursor-pointer text-xs font-semibold text-slate-500 hover:bg-slate-100 flex items-center gap-1.5"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </Button>
        <Button
          type="button"
          onClick={onSubmit}
          disabled={!canBook}
          className="cursor-pointer text-xs font-extrabold bg-slate-950 hover:bg-slate-800 text-white flex items-center gap-2 px-8 py-2.5 h-10 rounded-lg shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
          data-testid="booking.actions.submit"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-white" /> Booking...
            </>
          ) : active ? (
            `Book for ${formatInr(active.total_amount)}`
          ) : (
            "Book Shipment"
          )}
        </Button>
      </div>
    </div>
  );
}

/** Interactive B2B delivery mode toggle shown at the top of Step 2 (and Rate Calculator). */
export function DeliveryModeToggleBar({
  doorDelivery,
  isLoading,
  onChange,
}: {
  doorDelivery: boolean;
  isLoading?: boolean;
  onChange: (doorDelivery: boolean) => void;
}) {
  return (
    <div
      data-testid="quote-step-delivery-mode-toggle"
      className="flex flex-col gap-2.5 rounded-xl border border-slate-200 bg-slate-50/70 p-4"
    >
      <div className="space-y-0.5">
        <span className="text-xs font-extrabold uppercase tracking-wider text-slate-900">
          Delivery Type (Logismart Prime)
        </span>
        <p className="text-[11px] text-slate-600">
          Compare live prices between doorstep delivery and consignee self-pickup at the destination transport godown.
        </p>
      </div>
      <div className="inline-flex flex-wrap max-w-full w-fit rounded-lg border border-slate-200 bg-white p-1 shadow-2xs shrink-0">
        <button
          type="button"
          data-testid="quote-step-delivery-mode-door"
          aria-pressed={doorDelivery}
          disabled={isLoading}
          onClick={() => {
            if (!doorDelivery) onChange(true);
          }}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition-all cursor-pointer",
            doorDelivery
              ? "bg-primary text-primary-foreground shadow-xs"
              : "text-slate-600 hover:text-slate-900 hover:bg-slate-50",
          )}
        >
          <Truck className="h-3.5 w-3.5 shrink-0" />
          <span>Door Delivery</span>
        </button>
        <button
          type="button"
          data-testid="quote-step-delivery-mode-godown"
          aria-pressed={!doorDelivery}
          disabled={isLoading}
          onClick={() => {
            if (doorDelivery) onChange(false);
          }}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold transition-all cursor-pointer",
            !doorDelivery
              ? "bg-primary text-primary-foreground shadow-xs"
              : "text-slate-600 hover:text-slate-900 hover:bg-slate-50",
          )}
        >
          <Warehouse className="h-3.5 w-3.5 shrink-0" />
          <span>Godown Self-Pickup</span>
        </button>
      </div>
    </div>
  );
}

/** One service option card (greyed with the backend's reason when not bookable). */
export function ServiceOptionCard({
  option,
  isSelected,
  onSelect,
  doorDelivery,
}: {
  option: QuoteOption;
  isSelected: boolean;
  onSelect: (option: ServiceOption) => void;
  doorDelivery?: boolean;
}) {
  const meta = getOptionMeta(SERVICE_OPTION_OPTIONS, option.service_option);
  const Icon = meta?.icon;
  const serviceable = option.serviceable;
  const isPrime = option.service_option === ServiceOption.PRIME_SURFACE;
  const hasDoorDeliveryLine = Boolean(option.sell_lines?.some((line) => line.code === "DOOR_DELIVERY"));
  const isDoorDelivery = doorDelivery ?? hasDoorDeliveryLine;

  return (
    <button
      type="button"
      data-testid={optionCardTestId(option.service_option)}
      aria-pressed={isSelected}
      disabled={!serviceable}
      onClick={() => onSelect(option.service_option)}
      className={cn(
        "relative w-full min-w-0 overflow-hidden text-left border rounded-xl p-5 shadow-xs flex flex-col justify-start gap-3 transition-all duration-150",
        !serviceable && "bg-slate-50 border-slate-200 opacity-70 cursor-not-allowed",
        serviceable && isSelected && "bg-primary/5 border-primary shadow-3xs",
        serviceable && !isSelected && "bg-white border-slate-200 hover:border-slate-300 cursor-pointer",
      )}
    >
      <div className="flex justify-between items-start w-full gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {Icon && (
            <span className={cn("p-1.5 rounded-lg", isSelected ? "bg-primary/10 text-primary" : "bg-slate-100 text-slate-600")}>
              <Icon className="h-5 w-5" />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-900 truncate">{meta?.label ?? option.service_option}</p>
            {meta?.description && <p className="text-[11px] text-slate-500 truncate">{meta.description}</p>}
          </div>
        </div>
        {serviceable && isSelected && (
          <span className="h-5 w-5 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0">
            <Check className="h-3.5 w-3.5" />
          </span>
        )}
      </div>

      {serviceable ? (
        <div className="flex-1 flex flex-col gap-2 w-full min-w-0">
          {isPrime && (
            <div
              data-testid="prime-delivery-mode-badge"
              className={cn(
                "inline-flex items-center gap-1.5 w-fit max-w-full rounded-full border px-2.5 py-0.5 text-[10px] font-extrabold tracking-wide overflow-hidden",
                isDoorDelivery
                  ? "border-primary/30 bg-primary/10 text-primary"
                  : "border-emerald-200 bg-emerald-50 text-emerald-800",
              )}
            >
              {isDoorDelivery ? (
                <>
                  <Truck className="h-3 w-3 shrink-0" />
                  <span className="truncate">Door Delivery (incl. Door Delivery Charge)</span>
                </>
              ) : (
                <>
                  <Warehouse className="h-3 w-3 shrink-0" />
                  <span className="truncate">Godown Self-Pickup (₹0 Door Delivery Charge)</span>
                </>
              )}
            </div>
          )}
          <div className="flex items-baseline gap-1 text-slate-900">
            <span className="text-2xl font-extrabold">{formatInr(option.total_amount)}</span>
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">incl. GST</span>
          </div>
          <TransitLine option={option} />
          {isPrime && option.sell_lines && option.sell_lines.length > 0 && (
            <ul
              data-testid="prime-card-sell-lines"
              className="mt-auto pt-2 space-y-1 rounded-lg border border-slate-200/80 bg-white/90 p-2.5 text-[11px]"
            >
              {option.sell_lines.map((line) => (
                <li key={line.code} className="flex justify-between gap-2 text-slate-600">
                  <span className="truncate">{line.label}</span>
                  <span className="font-mono font-semibold text-slate-900 shrink-0">{formatInr(line.amount)}</span>
                </li>
              ))}
              {!hasDoorDeliveryLine && !isDoorDelivery && (
                <li className="flex justify-between gap-2 text-emerald-700 font-semibold">
                  <span className="truncate">Door delivery (Godown self-pickup)</span>
                  <span className="font-mono shrink-0">{formatInr(0)}</span>
                </li>
              )}
            </ul>
          )}
          {option.priced_from_cache && (
            <p className="flex items-center gap-1 text-[11px] font-medium text-amber-700" data-testid="booking.quote.cached">
              <Clock className="h-3.5 w-3.5" />
              Last known price
              {option.price_age_minutes != null ? ` (${option.price_age_minutes} min old)` : ""}; final price is checked when you book.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-1">
          <p className="flex items-center gap-1 text-[11px] font-extrabold uppercase tracking-wide text-red-600">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> Not available
          </p>
          <p className="text-xs text-slate-600 leading-snug" data-testid="booking.quote.unavailable-reason">
            {option.unavailable_reason || "This service can't take this shipment."}
          </p>
        </div>
      )}
    </button>
  );
}

/** Display format of the expected delivery date ("06 Nov 2026"), like Delhivery One. */
const DELIVERY_DATE_FORMAT = "dd MMM yyyy";

/**
 * Builds "Delivers in N days · by 06 Nov 2026" from the backend's transit facts.
 *
 * @param option - Quote card (transit days and/or ISO `expected_delivery_date`).
 * @returns The line, or null when the backend sent neither value.
 */
export function transitLineText(
  option: Pick<QuoteOption, "transit_days" | "expected_delivery_date">,
): string | null {
  if (option.transit_days == null && !option.expected_delivery_date) return null;
  const parsedDate = option.expected_delivery_date ? parseISO(option.expected_delivery_date) : null;
  const dateLabel =
    parsedDate && isValid(parsedDate) ? format(parsedDate, DELIVERY_DATE_FORMAT) : option.expected_delivery_date;
  const parts = [
    option.transit_days != null ? `Delivers in ${option.transit_days} day${option.transit_days === 1 ? "" : "s"}` : null,
    dateLabel ? `by ${dateLabel}` : null,
  ].filter(Boolean);
  return parts.join(" · ");
}

/** "Delivers in N days · by <date>" when the backend sent either value. */
function TransitLine({ option }: { option: QuoteOption }) {
  const text = transitLineText(option);
  if (!text) return null;
  return <p className="text-xs font-medium text-slate-600">{text}</p>;
}

/** Route + who pays what, for the selected option. */
function CashFlowSummary({
  option,
  isCod,
  pickup,
  delivery,
}: {
  option: QuoteOption;
  isCod: boolean;
  pickup?: RouteAddress | null;
  delivery?: RouteAddress | null;
}) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 bg-slate-50/40 border border-slate-200 p-6 rounded-xl min-w-0">
      <div className="lg:col-span-5 min-w-0 space-y-4 text-xs">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Delivery journey</h4>
        <RouteLine title="Pickup address" address={pickup} />
        <RouteLine title="Delivery address" address={delivery} />
      </div>
      <div className="lg:col-span-7 min-w-0 grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MoneyTile
          title="Collect at doorstep"
          amount={option.door_collectible_amount}
          hint={isCod ? "Cash the delivery agent collects" : "Prepaid: nothing to collect"}
          testId="booking.quote.door-collect"
        />
        <MoneyTile
          title="Shipping charges"
          amount={option.total_amount}
          hint="Billed to your wallet"
          testId="booking.quote.shipping"
        />
        <MoneyTile
          title="Sent back to you"
          amount={option.cod_remittance_amount}
          hint={isCod ? "COD remitted after delivery" : "No COD on this order"}
          testId="booking.quote.remittance"
        />
      </div>
    </div>
  );
}

function RouteLine({ title, address }: { title: string; address?: RouteAddress | null }) {
  const place = [address?.city, address?.state].filter(Boolean).join(", ");
  return (
    <div className="space-y-0.5">
      <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">{title}</span>
      <p className="font-bold text-slate-900 truncate">{address?.name || "New address"}</p>
      <p className="text-slate-500 truncate">
        {place}
        {address?.pincode ? ` - ${address.pincode}` : ""}
      </p>
    </div>
  );
}

function MoneyTile({ title, amount, hint, testId }: { title: string; amount?: number; hint: string; testId: string }) {
  return (
    <div className="bg-white border border-slate-200 p-4 rounded-xl space-y-1 min-w-0 overflow-hidden">
      <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider block truncate">{title}</span>
      <p className="text-xl font-black text-slate-950 font-mono truncate" data-testid={testId}>
        {formatInr(amount)}
      </p>
      <span className="text-[10px] text-slate-500 block leading-tight">{hint}</span>
    </div>
  );
}

/** Backend `sell_lines` breakup of the selected option + its total. */
export function PriceBreakup({ option, footer }: { option: QuoteOption; footer?: ReactNode }) {
  return (
    <div className="bg-slate-50/40 border border-slate-200 rounded-xl p-6 space-y-4 min-w-0 overflow-hidden">
      <h3 className="text-xs font-extrabold text-slate-800 uppercase tracking-wider flex items-center gap-2 border-b border-slate-200/60 pb-2.5">
        <Receipt className="h-4 w-4 text-slate-500 shrink-0" /> Price breakup
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 min-w-0">
        <ul className="space-y-2 text-xs min-w-0">
          {(option.sell_lines ?? []).map((line) => (
            <li key={line.code} className="flex justify-between gap-2 text-slate-600 min-w-0">
              <span className="truncate">{line.label}</span>
              <span className="font-medium text-slate-900 font-mono shrink-0">{formatInr(line.amount)}</span>
            </li>
          ))}
          <li className="flex items-center gap-2 pt-2 text-slate-500 flex-wrap">
            <Scale className="h-3.5 w-3.5 shrink-0" /> Chargeable weight: <strong className="text-slate-900">{formatKg(option.chargeable_weight_kg)}</strong>
          </li>
        </ul>
        <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-1 min-w-0 overflow-hidden">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Total shipping cost</span>
          <p className="text-3xl font-extrabold font-mono text-primary truncate" data-testid="booking.quote.total">
            {formatInr(option.total_amount)}
          </p>
          <p className="text-[11px] text-slate-500 pt-2">
            The price is checked again when you book. If it changed, we ask you before booking.
          </p>
          {footer}
        </div>
      </div>
    </div>
  );
}

/** COD was requested but the tenant has not enabled it yet. */
function CodUnavailableAlert({ reason, onBack }: { reason?: string | null; onBack: () => void }) {
  return (
    <div
      className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900"
      data-testid="booking.quote.cod-unavailable"
    >
      <p className="text-sm">
        <strong>Cash on Delivery isn&apos;t available.</strong>{" "}
        {reason || "COD is not enabled for this account yet."} Go back and switch COD off to book this as prepaid.
      </p>
      <Button type="button" variant="outline" size="sm" onClick={onBack}>
        Edit details
      </Button>
    </div>
  );
}

/** A-26: ask the user to confirm an unusually heavy shipment before booking. */
function HeavyWeightConfirm({
  thresholdKg,
  checked,
  onChange,
}: {
  thresholdKg: number;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label
      className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900 cursor-pointer"
      data-testid="booking.quote.heavy-weight"
    >
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 accent-primary"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        data-testid="booking.quote.heavy-weight-confirm"
      />
      <span className="text-sm">
        <strong>This shipment is unusually heavy (over {formatKg(thresholdKg)}).</strong> Please check the weight and
        box sizes. A typo (for example 500 kg instead of 5 kg) is billed as entered. Tick to confirm they are correct.
      </span>
    </label>
  );
}

function SkeletonCard() {
  return (
    <div className="bg-white border border-slate-100 rounded-xl p-5 shadow-xs h-36 space-y-3 animate-pulse">
      <div className="h-4 bg-slate-200 rounded w-2/3" />
      <div className="h-8 bg-slate-100 rounded w-1/2" />
      <div className="h-3 bg-slate-200 rounded w-3/4" />
    </div>
  );
}
