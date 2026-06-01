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
        estimated_days = 5  # Default surface road delivery

        if request.service_type == ServiceType.SURFACE_TRAIN:
            # Rail logistics has a minor surcharge but is faster than road
            service_surcharge = base_charge * 0.15
            estimated_days = 3
        elif request.service_type == ServiceType.AIR:
            # Air freight delivers in 1 day with a 60% premium
            service_surcharge = base_charge * 0.60
            estimated_days = 1

        # 4. Calculate Auxiliary Surcharges & COD Fee
        # Fuel surcharge is 10% of freight subtotal
        fuel_surcharge = (base_charge + service_surcharge) * 0.10
        # Network surcharge is flat INR 25
        network_surcharge = 25.0

        # COD Fee is 2.0% of the commercial Shipment Total Value, only if Cash on Delivery is requested
        cod_fee = 0.0
        if request.is_cod and request.shipment_total_value > 0:
            cod_fee = request.shipment_total_value * 0.02

        # 5. Calculate Taxes & Total Logistics Charge
        subtotal = base_charge + service_surcharge + fuel_surcharge + network_surcharge + cod_fee
        tax_amount = subtotal * cls.TAX_RATE
        total_amount = subtotal + tax_amount

        # 6. Return the complete "Receipt" breakdown
        return RateCalculationResponse(
            chargeable_weight=round(total_chargeable_weight, 2),
            base_charge=round(base_charge, 2),
            service_surcharge=round(service_surcharge, 2),
            fuel_surcharge=round(fuel_surcharge, 2),
            network_surcharge=round(network_surcharge, 2),
            cod_fee=round(cod_fee, 2),
            tax_amount=round(tax_amount, 2),
            total_amount=round(total_amount, 2),
            estimated_days=estimated_days,
        )
