"""Page objects, one class per screen (ship-readiness plan E3)."""

from .base_page import BasePage
from .booking_page import (
    B2BBookingPage,
    B2CBookingPage,
    BookingInput,
    BookingResult,
    PackageInput,
)
from .finance_pages import InvoicesPage, RemittancesPage, WalletPage
from .login_page import LoginPage
from .ops_page import OpsMobilePage
from .pickup_pages import PickupDispatchDialog, PickupRequestsPage
from .shipment_pages import (
    MeasurementDialog,
    ShipmentDetailPage,
    ShipmentEditPage,
)
from .weight_mismatch_page import WeightMismatchPage

__all__ = [
    "B2BBookingPage",
    "B2CBookingPage",
    "BasePage",
    "BookingInput",
    "BookingResult",
    "InvoicesPage",
    "LoginPage",
    "MeasurementDialog",
    "OpsMobilePage",
    "PackageInput",
    "PickupDispatchDialog",
    "PickupRequestsPage",
    "RemittancesPage",
    "ShipmentDetailPage",
    "ShipmentEditPage",
    "WalletPage",
    "WeightMismatchPage",
]
