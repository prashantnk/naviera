from enum import Enum


class ExceptionCategory(str, Enum):
    """
    Delivery-exception buckets shown on the Exceptions & NDR pages.

    B2C (Delhivery Domestic) uses four groups: SHIPMENT_EXCEPTIONS, NDR,
    PICKUP_FAILED and NON_ACTIONABLE. B2B (Delhivery Cargo) uses the eleven
    "on hold" categories (NDR is shared by both flows).
    Not persisted: categories are derived server-side from the NDR reason,
    the shipment direction and whether the merchant can still act.
    """

    SHIPMENT_EXCEPTIONS = "SHIPMENT_EXCEPTIONS"
    NDR = "NDR"
    PICKUP_FAILED = "PICKUP_FAILED"
    NON_ACTIONABLE = "NON_ACTIONABLE"
    PAYMENT_DISPUTE = "PAYMENT_DISPUTE"
    DAMAGES = "DAMAGES"
    EWAY_BILL = "EWAY_BILL"
    CONSIGNEE_DETAILS = "CONSIGNEE_DETAILS"
    DOCUMENT_NEEDED = "DOCUMENT_NEEDED"
    SHORT_SHIPMENTS = "SHORT_SHIPMENTS"
    APPOINTMENT_NEEDED = "APPOINTMENT_NEEDED"
    FREIGHT_COLLECTION = "FREIGHT_COLLECTION"
    ADDITIONAL_CHARGES = "ADDITIONAL_CHARGES"
    MEASURED_WEIGHT = "MEASURED_WEIGHT"
