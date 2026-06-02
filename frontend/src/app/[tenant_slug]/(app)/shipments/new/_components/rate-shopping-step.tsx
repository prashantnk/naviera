// frontend/src/app/[tenant_slug]/(app)/shipments/new/_components/rate-shopping-step.tsx
"use client";

import { ServiceQuote, ServiceType, RateCalculationResponse, AddressRead } from "@/api_client";
import { Button } from "@/components/ui/button";
import { Plane, Train, Truck, Scale, Receipt, ArrowLeft, Check, AlertTriangle, Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useFormContext } from "react-hook-form";
import { ForwardShipmentFormValues } from "@/lib/validations/shipment";

interface RateShoppingStepProps {
  rateQuotes: ServiceQuote[];
  isLoadingRates: boolean;
  selectedQuote: ServiceQuote | null;
  setSelectedQuote: (quote: ServiceQuote | null) => void;
  onBack: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isCod: boolean;
  addShippingToCod: boolean;
  savedAddresses: AddressRead[];
}

const SERVICE_NAMES: Record<ServiceType, string> = {
  [ServiceType.AIR]: "Air Cargo (Fastest)",
  [ServiceType.SURFACE_TRAIN]: "Surface Train (Eco)",
  [ServiceType.SURFACE_ROAD]: "Surface Road (Standard)",
};

const SERVICE_ICONS: Record<ServiceType, React.ReactNode> = {
  [ServiceType.AIR]: <Plane className="h-5 w-5" />,
  [ServiceType.SURFACE_TRAIN]: <Train className="h-5 w-5" />,
  [ServiceType.SURFACE_ROAD]: <Truck className="h-5 w-5" />,
};

export function RateShoppingStep({
  rateQuotes,
  isLoadingRates,
  selectedQuote,
  setSelectedQuote,
  onBack,
  onSubmit,
  isSubmitting,
  isCod,
  addShippingToCod,
  savedAddresses,
}: RateShoppingStepProps) {
  const { getValues } = useFormContext<ForwardShipmentFormValues>();
  const values = getValues();

  // Resolve segment locations
  const pickupAddr = values.pickup_address_id
    ? savedAddresses.find((a) => a.id === values.pickup_address_id)
    : values.new_pickup_address;

  const deliveryAddr = values.delivery_address_id
    ? savedAddresses.find((a) => a.id === values.delivery_address_id)
    : values.new_delivery_address;

  const activeQuoteDetails: RateCalculationResponse | null = selectedQuote?.quote || null;
  const shippingCost = activeQuoteDetails?.total_amount || 0;
  const codAmount = values.payment_details?.cod_amount || 0;
  const isCodActive = isCod;
  const paymentMode = values.payment_details?.freight_payment_mode;

  // Cash Remittance Mathematics
  let totalCustomerPays = 0;
  let shippingPaidBy = "Sender";
  let senderNetRemittance = 0;

  if (paymentMode === "TO_PAY") {
    shippingPaidBy = "Receiver (Customer)";
    totalCustomerPays = shippingCost + (isCodActive ? codAmount : 0);
    senderNetRemittance = isCodActive ? codAmount : 0;
  } else {
    shippingPaidBy = "Sender (You)";
    if (isCodActive) {
      if (addShippingToCod) {
        // Shipping Z was added to COD, customer pays codAmount + Z
        totalCustomerPays = codAmount + shippingCost;
        // Z covers shipping, sender gets codAmount back
        senderNetRemittance = codAmount;
      } else {
        // Shipping paid separately by sender, customer pays codAmount
        totalCustomerPays = codAmount;
        senderNetRemittance = codAmount;
      }
    } else {
      totalCustomerPays = 0;
      senderNetRemittance = 0;
    }
  }

  // Map flat backend keys to map-friendly array, filtering out inactive surcharges
  const surchargesList = [
    {
      name: "Speed Premium Surcharge",
      amount: activeQuoteDetails?.pricing_breakdown?.service_surcharge,
    },
    {
      name: "Fuel Surcharge & DPH",
      amount: activeQuoteDetails?.pricing_breakdown?.fuel_surcharge,
    },
    {
      name: "Network Access Surcharge",
      amount: activeQuoteDetails?.pricing_breakdown?.network_surcharge,
    },
    {
      name: "Oversized Cargo Surcharge",
      amount: activeQuoteDetails?.pricing_breakdown?.oversized_surcharge,
    },
    {
      name: "RTO Return Surcharge",
      amount: activeQuoteDetails?.pricing_breakdown?.rto_surcharge,
    },
  ].filter((item) => item.amount && item.amount > 0);
  // Keep selected quote in sync with the refreshed rateQuotes list
  useEffect(() => {
    if (rateQuotes.length > 0) {
      // Find if there's a quote in the new list that matches the currently selected service type
      const matchingQuote = selectedQuote
        ? rateQuotes.find((q) => q.service_type === selectedQuote.service_type && q.serviceable)
        : null;

      if (matchingQuote) {
        // Update reference to the refreshed quote
        setSelectedQuote(matchingQuote);
      } else {
        // Otherwise, fallback to the first serviceable quote
        const firstServiceable = rateQuotes.find((q) => q.serviceable);
        setSelectedQuote(firstServiceable || null);
      }
    } else {
      setSelectedQuote(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rateQuotes, setSelectedQuote]);



  return (
    <div className="space-y-6 animate-in fade-in duration-200">

      {/* Shipping Summary & Cash Flow */}
      {activeQuoteDetails && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 bg-slate-50/40 border border-slate-200 p-6 rounded-xl shadow-3xs animate-in fade-in duration-250">
          {/* Journey Route segment (col-span-5) */}
          <div className="lg:col-span-5 space-y-4 border-b lg:border-b-0 lg:border-r border-slate-200/80 pb-4 lg:pb-0 lg:pr-6">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
              Delivery Journey
            </h4>
            <div className="flex items-start gap-4 pt-1">
              <div className="flex flex-col items-center justify-center h-full py-1.5 shrink-0">
                <div className="h-2.5 w-2.5 rounded-full bg-slate-900 border-2 border-white ring-2 ring-slate-900/20"></div>
                <div className="w-0.5 h-10 bg-dashed border-l border-slate-300 my-1"></div>
                <div className="h-2.5 w-2.5 rounded-full bg-emerald-600 border-2 border-white ring-2 ring-emerald-600/20"></div>
              </div>
              <div className="space-y-5 text-xs">
                <div className="space-y-0.5">
                  <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">Pickup Address</span>
                  <p className="font-bold text-slate-900 truncate">{pickupAddr?.name || "Custom Pickup Address"}</p>
                  <p className="text-slate-500 truncate max-w-[220px]">{pickupAddr?.city}, {pickupAddr?.state} - {pickupAddr?.pincode}</p>
                </div>
                <div className="space-y-0.5">
                  <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">Delivery Address</span>
                  <p className="font-bold text-slate-900 truncate">{deliveryAddr?.name || "Custom Delivery Address"}</p>
                  <p className="text-slate-500 truncate max-w-[220px]">{deliveryAddr?.city}, {deliveryAddr?.state} - {deliveryAddr?.pincode}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Cash Flow segment (col-span-7) */}
          <div className="lg:col-span-7 space-y-4">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
              Cash Flow & Remittance Details
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
              {/* Doorstep cash to collect */}
              <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-2xs space-y-1">
                <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider block">
                  Collect at Doorstep
                </span>
                <p className="text-xl font-black text-slate-950 font-mono">
                  ₹{Math.round(totalCustomerPays).toLocaleString()}
                </p>
                <span className="text-[9px] text-slate-400 font-medium block leading-tight">
                  {isCodActive 
                    ? `COD amount ${paymentMode === "TO_PAY" ? "+ Shipping fee" : (addShippingToCod ? "+ Shipping fee" : "")}`
                    : (paymentMode === "TO_PAY" ? "Shipping Charges" : "Prepaid - No cash to collect")}
                </span>
              </div>

              {/* Shipping Cost paid by */}
              <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-2xs space-y-1">
                <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider block">
                  Shipping Charges
                </span>
                <p className="text-xl font-black text-slate-950 font-mono">
                  ₹{Math.round(shippingCost).toLocaleString()}
                </p>
                <span className="text-[9px] text-slate-500 font-bold block leading-tight">
                  Paid by: <span className="text-primary font-black">{shippingPaidBy}</span>
                </span>
              </div>

              {/* Sender Remittance Payout */}
              <div className="bg-emerald-50/30 border border-emerald-200 p-4 rounded-xl shadow-2xs space-y-1">
                <span className="text-emerald-700 text-[10px] uppercase font-bold tracking-wider block">
                  Sent to Sender (You)
                </span>
                <p className="text-xl font-black text-emerald-700 font-mono">
                  ₹{Math.round(senderNetRemittance).toLocaleString()}
                </p>
                <span className="text-[9px] text-emerald-600 font-bold block leading-tight">
                  {isCodActive 
                    ? "COD cash remittance" 
                    : "Prepaid shipment (No collection)"}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Rate Shipping Matrix */}
      <div className="space-y-4 pt-2">
        <div className="border-b border-slate-100 pb-2.5">
          <h3 className="text-base font-extrabold text-slate-950 tracking-tight flex items-center gap-2.5">
            <Receipt className="h-4.5 w-4.5 text-primary shrink-0" />
            <span>Choose Shipping Mode</span>
          </h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {isLoadingRates ? (
            // Pulse skeleton loaders
            Array.from({ length: 3 }).map((_, idx) => (
              <div
                key={idx}
                className="bg-white border border-slate-100 rounded-xl p-5 shadow-xs h-36 space-y-3 animate-pulse flex flex-col justify-between"
              >
                <div className="flex justify-between items-center">
                  <div className="h-4 bg-slate-200 rounded w-2/3"></div>
                  <div className="h-5 bg-slate-200 rounded-full w-7"></div>
                </div>
                <div className="h-8 bg-slate-100 rounded w-1/2"></div>
                <div className="h-3 bg-slate-200 rounded w-3/4"></div>
              </div>
            ))
          ) : (
            rateQuotes.map((item) => {
              const isSelected = selectedQuote?.service_type === item.service_type;
              const isServiceable = item.serviceable;
              const quote = item.quote;

              return (
                <div
                  key={item.service_type}
                  onClick={() => {
                    if (isServiceable) {
                      setSelectedQuote(item);
                    }
                  }}
                  className={`relative border rounded-xl p-5 shadow-xs flex flex-col justify-between transition-all duration-150 select-none ${
                    !isServiceable
                      ? "bg-slate-50 border-slate-200 opacity-60 cursor-not-allowed"
                      : isSelected
                      ? "bg-primary/5 border-primary shadow-3xs cursor-pointer scale-[1.01]"
                      : "bg-white border-slate-200 hover:border-slate-300 cursor-pointer"
                  }`}
                  title={!isServiceable ? item.error_message || "Service speed unserviceable for this route." : undefined}
                >
                  <div className="flex justify-between items-start w-full">
                    <div className="flex items-center gap-2">
                      <div
                        className={`p-1.5 rounded-lg ${
                          !isServiceable
                            ? "bg-slate-100 text-slate-400"
                            : isSelected
                            ? "bg-primary/10 text-primary"
                            : "bg-slate-50 text-slate-600"
                        }`}
                      >
                        {SERVICE_ICONS[item.service_type]}
                      </div>
                      <span className="text-xs font-bold text-slate-900 truncate">
                        {SERVICE_NAMES[item.service_type]}
                      </span>
                    </div>
                    {isServiceable && isSelected && (
                      <div className="h-5 w-5 rounded-full bg-primary text-white flex items-center justify-center">
                        <Check className="h-3.5 w-3.5" />
                      </div>
                    )}
                  </div>

                  <div className="mt-4">
                    {isServiceable && quote ? (
                      <div>
                        <div className="flex items-baseline gap-0.5 text-slate-900">
                          <span className="text-2xl font-extrabold">₹{Math.round(quote.total_amount)}</span>
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">
                            Total
                          </span>
                        </div>
                        <p className="text-[10px] font-medium text-slate-500 mt-1">
                          Est. Transit Days: <strong>{quote.pricing_breakdown?.transit_days || "2-4"} days</strong>
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-1">
                        <div className="flex items-center gap-1 text-red-650">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                          <span className="text-[10px] font-extrabold uppercase tracking-wide text-red-500">
                            Unserviceable
                          </span>
                        </div>
                        <p className="text-[9px] text-slate-400 line-clamp-2 leading-snug">
                          {item.error_message || "No active routing lanes currently cover these pin-codes."}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Chargeable Weight Banner placed cleanly below selectors */}
        {activeQuoteDetails && (
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 px-4 flex items-center gap-3 text-slate-700 shadow-3xs animate-in slide-in-from-top-2 duration-200 mt-4">
            <Scale className="h-4 w-4 text-primary shrink-0" />
            <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3 text-xs">
              <p className="text-slate-800 font-medium leading-none">
                Total Chargeable Weight: <strong className="text-slate-950 font-bold">{activeQuoteDetails.chargeable_weight.toFixed(2)} kg</strong>
              </p>
              {activeQuoteDetails.pricing_breakdown && (
                <span className="text-[11px] text-slate-500 font-normal leading-none">
                  (Calculated as {Number(activeQuoteDetails.pricing_breakdown.total_volumetric_weight ?? 0).toFixed(2)} kg volumetric vs {Number(activeQuoteDetails.pricing_breakdown.total_actual_weight ?? 0).toFixed(2)} kg actual).
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Granular Billing Ledger / Surcharge Breakdown */}
      {activeQuoteDetails && (
        <div className="bg-slate-50/40 border border-slate-200 rounded-xl p-6 space-y-4 animate-in fade-in duration-200">
          <div className="border-b border-slate-200/60 pb-2.5">
            <h3 className="text-xs font-extrabold text-slate-800 uppercase tracking-wider flex items-center gap-2">
              <Receipt className="h-4 w-4 text-slate-500 shrink-0" /> Shipping Cost Breakup
            </h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Left list: granular line items */}
            <div className="space-y-2 text-xs">
              <div className="flex justify-between text-slate-600">
                <span>Base Freight Charge</span>
                <span className="font-medium text-slate-900 font-mono">₹{activeQuoteDetails.base_charge.toFixed(2)}</span>
              </div>
              {surchargesList.map((item, index) => (
                <div key={index} className="flex justify-between text-slate-600 animate-in fade-in">
                  <span>{item.name}</span>
                  <span className="font-medium text-slate-900 font-mono">₹{Number(item.amount || 0).toFixed(2)}</span>
                </div>
              ))}
              {/* COD doorbell fee if is_cod is selected */}
              {isCod && (
                <div className="flex justify-between text-indigo-700 bg-indigo-50/30 px-2 py-1 rounded border border-indigo-100/40 animate-in fade-in">
                  <span>Doorstep COD Collection Fee</span>
                  <span className="font-bold font-mono">₹{Number(activeQuoteDetails?.pricing_breakdown?.cod_fee ?? 0).toFixed(2)}</span>
                </div>
              )}
              <div className="flex justify-between text-slate-600">
                <span>GST / CGST (18%)</span>
                <span className="font-medium text-slate-900 font-mono">₹{activeQuoteDetails.tax_amount.toFixed(2)}</span>
              </div>
            </div>

            {/* Right summary: total and actionable details */}
            <div className="bg-white border border-slate-200 rounded-xl p-4.5 flex flex-col justify-between shadow-2xs">
              <div className="space-y-1">
                <span className="text-[9px] font-bold uppercase tracking-wider text-slate-400">
                  Total Shipping Cost
                </span>
                <div className="flex items-baseline gap-1 mt-1 text-primary">
                  <span className="text-3xl font-extrabold font-mono">₹{activeQuoteDetails.total_amount.toFixed(2)}</span>
                  <span className="text-[10px] font-bold uppercase tracking-widest text-primary/70">
                    NET INR
                  </span>
                </div>
              </div>

              <div className="mt-4 border-t border-slate-100 pt-3.5 text-[10px] text-slate-450 leading-relaxed">
                <p>
                  Shipping cost will be based on total weight and shipping mode
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form actions / footer triggers */}
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
          disabled={isSubmitting || !selectedQuote}
          className="cursor-pointer text-xs font-extrabold bg-slate-950 hover:bg-slate-850 text-white flex items-center gap-2 px-8 py-2.5 h-10 rounded-lg shadow-md transition-all hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-white" /> Booking...
            </>
          ) : (
            "Book Shipment"
          )}
        </Button>
      </div>
    </div>
  );
}
