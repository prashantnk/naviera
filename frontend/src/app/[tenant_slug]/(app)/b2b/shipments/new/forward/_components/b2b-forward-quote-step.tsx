// frontend/src/app/[tenant_slug]/(app)/b2b/shipments/new/forward/_components/b2b-forward-quote-step.tsx
"use client";

/**
 * B2B Forward Booking Wizard Step 2 (Carrier Quote Selection).
 *
 * Re-exports the shared `QuoteStep` and `DeliveryModeToggleBar` so B2B Step 2
 * renders the live "Delivery Type: [🚚 Door Delivery] [🏭 Godown Self-Pickup]"
 * toggle, the delivery-mode badge on Logismart Prime cards, and itemized `sell_lines`.
 */
export {
  DeliveryModeToggleBar,
  PriceBreakup,
  QuoteStep as B2BForwardQuoteStep,
  QuoteStep,
  ServiceOptionCard,
  type QuoteStepProps,
} from "@/components/booking/quote-step";
