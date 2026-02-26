# backend/app/services/pricing.py
from app.models.pickups import ServiceType
from app.schemas.v1.pickups import RateCalculationRequest, RateCalculationResponse


class PricingEngine:
    """
    Core business logic for calculating shipping rates based on standard
    logistics algorithms (Actual vs Volumetric Weight).
    """

    # Industry standard volumetric divisor (cm3 / 5000 = kg)
    VOLUMETRIC_DIVISOR = 5000.0
    BASE_RATE_PER_KG = 50.0  # INR 50 per KG
    TAX_RATE = 0.18  # 18% GST

    @classmethod
    def calculate_rate(cls, request: RateCalculationRequest) -> RateCalculationResponse:
        total_chargeable_weight = 0.0

        # 1. Calculate Chargeable Weight for all packages
        for pkg in request.packages:
            # Volumetric weight = (L * B * H) / 5000
            volumetric_weight = (
                pkg.length * pkg.breadth * pkg.height
            ) / cls.VOLUMETRIC_DIVISOR

            # Multiply by number of boxes
            total_volumetric = volumetric_weight * pkg.box_count
            total_actual = pkg.weight * pkg.box_count

            # Chargeable weight is always the HIGHER of actual vs volumetric
            chargeable = max(total_actual, total_volumetric)
            total_chargeable_weight += chargeable

        # 2. Calculate Base Charge
        base_charge = total_chargeable_weight * cls.BASE_RATE_PER_KG

        # 3. Apply Service Type Multipliers
        service_surcharge = 0.0
        estimated_days = 5  # Default surface delivery

        if request.service_type == ServiceType.EXPRESS:
            # Express costs 50% more and delivers in 2 days
            service_surcharge = base_charge * 0.5
            estimated_days = 2

        # 4. Calculate Taxes & Total
        subtotal = base_charge + service_surcharge
        tax_amount = subtotal * cls.TAX_RATE
        total_amount = subtotal + tax_amount

        # 5. Return the "Receipt" breakdown
        return RateCalculationResponse(
            chargeable_weight=round(total_chargeable_weight, 2),
            base_charge=round(base_charge, 2),
            service_surcharge=round(service_surcharge, 2),
            tax_amount=round(tax_amount, 2),
            total_amount=round(total_amount, 2),
            estimated_days=estimated_days,
        )
