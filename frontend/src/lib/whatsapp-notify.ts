// frontend/src/lib/whatsapp-notify.ts

/**
 * Pure helper utilities for generating instant Consignee WhatsApp (`wa.me`)
 * and Email (`mailto:`) notification links across Order Detail and Operations
 * Control Tower views.
 *
 * Spring Boot equivalent: A stateless notification template builder bean
 * (`ConsigneeNotificationLinkBuilder`) formatting deep links for client triggers.
 */

import { PickupStatus } from "@/api_client";

export type ConsigneeNotificationStage =
  | "BOOKED"
  | "IN_TRANSIT"
  | "OUT_FOR_DELIVERY"
  | "DELIVERED"
  | "EXCEPTION";

/**
 * Shipment status -> consignee message stage (E-08). Only a real Out-for-Delivery parcel
 * gets the "out for delivery today + OTP" text; RTO / closed parcels get no consignee message.
 */
const CONSIGNEE_STAGE_BY_STATUS: Readonly<Partial<Record<PickupStatus, ConsigneeNotificationStage>>> = {
  [PickupStatus.DRAFT]: "BOOKED",
  [PickupStatus.OPEN]: "BOOKED",
  [PickupStatus.ASSIGNED]: "BOOKED",
  [PickupStatus.IN_TRANSIT]: "IN_TRANSIT",
  [PickupStatus.OUT_FOR_DELIVERY]: "OUT_FOR_DELIVERY",
  [PickupStatus.COMPLETED]: "DELIVERED",
  [PickupStatus.EXCEPTION]: "EXCEPTION",
};

/**
 * The consignee message stage for a shipment status.
 *
 * @param status - Current shipment status.
 * @returns The stage, or null when the consignee should not be messaged (RTO, cancelled, lost…).
 */
export function consigneeStageForStatus(
  status: PickupStatus
): ConsigneeNotificationStage | null {
  return CONSIGNEE_STAGE_BY_STATUS[status] ?? null;
}

export interface ConsigneeNotificationParams {
  phone?: string | null;
  email?: string | null;
  consigneeName?: string | null;
  trackingId: string;
  tenantName: string;
  trackingUrl: string;
  stage: ConsigneeNotificationStage;
  deliveryOtp?: string | null;
  exceptionReason?: string | null;
}

const INDIA_COUNTRY_PREFIX = "91";
const STANDARD_INDIAN_MOBILE_LENGTH = 10;
const ZERO_PREFIXED_MOBILE_LENGTH = 11;

/**
 * Normalizes an Indian phone number for WhatsApp `wa.me` deep links.
 * Strips spaces, dashes, and plus symbols; prefixes `91` when a 10-digit
 * local mobile number is provided.
 */
export function normalizeIndianPhoneForWhatsApp(
  rawPhone?: string | null
): string {
  if (!rawPhone) {
    return "";
  }
  const digitsOnly = rawPhone.replace(/\D/g, "");
  if (!digitsOnly) {
    return "";
  }
  if (digitsOnly.length === STANDARD_INDIAN_MOBILE_LENGTH) {
    return `${INDIA_COUNTRY_PREFIX}${digitsOnly}`;
  }
  if (
    digitsOnly.length === ZERO_PREFIXED_MOBILE_LENGTH &&
    digitsOnly.startsWith("0")
  ) {
    const trimmed = digitsOnly.slice(1);
    return `${INDIA_COUNTRY_PREFIX}${trimmed}`;
  }
  return digitsOnly;
}

/**
 * Whether the number can be used in a `wa.me` link (OPSX-25). An empty number would open
 * WhatsApp's contact picker, so the rider could send the message (and OTP) to anyone.
 *
 * @param rawPhone - Consignee phone as stored.
 * @returns True when at least a full 10-digit mobile number is present.
 */
export function hasWhatsAppPhone(rawPhone?: string | null): boolean {
  return (
    normalizeIndianPhoneForWhatsApp(rawPhone).length >= STANDARD_INDIAN_MOBILE_LENGTH
  );
}

/**
 * Builds the structured subject and message body for a consignee update.
 */
export function buildConsigneeNotificationMessage(
  params: ConsigneeNotificationParams
): { subject: string; body: string } {
  const recipientName = params.consigneeName?.trim() || "Customer";
  const brandName = params.tenantName?.trim() || "Logismart";
  const awb = params.trackingId;
  const link = params.trackingUrl;

  if (params.stage === "OUT_FOR_DELIVERY") {
    const otpLine = params.deliveryOtp
      ? `Delivery Verification OTP: *${params.deliveryOtp}* (Please share this 6-digit OTP with the delivery executive at your doorstep to confirm receipt).`
      : "Please keep your 6-digit doorstep verification OTP ready for the delivery executive.";

    const lines = [
      `Hello ${recipientName},`,
      `Your ${brandName} shipment (AWB: *${awb}*) is *Out for Delivery* today!`,
      otpLine,
      `Live Tracking: ${link}`,
      `Thank you for shipping with ${brandName}.`,
    ];
    return {
      subject: `${brandName} — Out for Delivery (AWB ${awb})`,
      body: lines.join("\n\n"),
    };
  }

  if (params.stage === "IN_TRANSIT") {
    const lines = [
      `Hello ${recipientName},`,
      `Your ${brandName} shipment (AWB: *${awb}*) is on its way.`,
      "You will get your 6-digit delivery OTP on the day it goes out for delivery.",
      `Live Tracking: ${link}`,
      `Thank you for shipping with ${brandName}.`,
    ];
    return {
      subject: `${brandName} — In Transit (AWB ${awb})`,
      body: lines.join("\n\n"),
    };
  }

  if (params.stage === "DELIVERED") {
    const lines = [
      `Hello ${recipientName},`,
      `Your ${brandName} shipment (AWB: *${awb}*) has been *Delivered* and verified via doorstep POD.`,
      `View Delivery Summary: ${link}`,
      `Thank you for choosing ${brandName}.`,
    ];
    return {
      subject: `${brandName} — Shipment Delivered (AWB ${awb})`,
      body: lines.join("\n\n"),
    };
  }

  if (params.stage === "EXCEPTION") {
    const reasonText = params.exceptionReason
      ? params.exceptionReason.replace(/_/g, " ")
      : "Action Required";
    const lines = [
      `Hello ${recipientName},`,
      `We encountered a delivery exception on your ${brandName} shipment (AWB: *${awb}*): *${reasonText}*.`,
      `Check Status & Updates: ${link}`,
      `Our operations team is working to resolve this promptly.`,
    ];
    return {
      subject: `${brandName} — Delivery Exception Update (AWB ${awb})`,
      body: lines.join("\n\n"),
    };
  }

  const bookedLines = [
    `Hello ${recipientName},`,
    `Your shipment with ${brandName} has been booked under AWB *${awb}*.`,
    `Track Live Status: ${link}`,
    `Thank you for choosing ${brandName}.`,
  ];
  return {
    subject: `${brandName} — Shipment Booked (AWB ${awb})`,
    body: bookedLines.join("\n\n"),
  };
}

/**
 * Generates a `https://wa.me/<phone>?text=<message>` URL for instant WhatsApp
 * notification dispatch to the consignee.
 */
export function buildWhatsAppConsigneeUrl(
  params: ConsigneeNotificationParams
): string {
  const cleanPhone = normalizeIndianPhoneForWhatsApp(params.phone);
  const { body } = buildConsigneeNotificationMessage(params);
  const escapedBody =
    encodeURIComponent(body);
  const baseUrl = "https://wa.me/";
  return `${baseUrl}${cleanPhone}?text=${escapedBody}`;
}

/**
 * Generates a fallback `mailto:` link with pre-filled subject and body
 * for consignee email notifications.
 */
export function buildMailtoConsigneeUrl(
  params: ConsigneeNotificationParams
): string {
  const recipientEmail = params.email?.trim() || "";
  const { subject, body } = buildConsigneeNotificationMessage(params);
  const plainBody = body.replace(/\*/g, "");
  const escapedSubject =
    encodeURIComponent(subject);
  const escapedBody =
    encodeURIComponent(plainBody);
  return `mailto:${recipientEmail}?subject=${escapedSubject}&body=${escapedBody}`;
}
