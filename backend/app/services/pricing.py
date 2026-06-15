# backend/app/services/pricing.py
import math
from app.models.pickups import ServiceType, DimensionUnit, WeightUnit, ShipmentType
from app.schemas.v1.pickups import (
    RateCalculationRequest,
    RateCalculationResponse,
    BulkRateCalculationRequest,
    BulkRateCalculationResponse,
    ServiceQuote,
    QuoteSpecification,
)


class PricingEngine:
    """
    Core business logic for calculating shipping rates based on standard
    logistics algorithms (Actual vs Volumetric Weight).
    Adheres to strict multi-tenant carrier economics and pricing guidelines.
    """

    # Core freight metrics
    BASE_RATE_PER_KG: float = 50.0  # INR 50 per KG
    TAX_RATE: float = 0.18  # 18% GST

    # Volumetric & weight limits
    AIR_VOLUMETRIC_DIVISOR: float = 5000.0
    SURFACE_VOLUMETRIC_DIVISOR: float = 4500.0
    MINIMUM_WEIGHT_FLOOR: float = 0.5
    SLAB_ROUNDING_BASE: float = 2.0

    B2B_MINIMUM_WEIGHT_FLOOR: float = 10.0
    B2B_SLAB_ROUNDING_BASE: float = 1.0
    B2B_DOCKET_CHARGE_INR: float = 50.0
    B2B_FOV_PERCENTAGE: float = 0.002
    B2B_FOV_MINIMUM_INR: float = 50.0

    # Dimensional normalizations to CM
    INCH_TO_CM: float = 2.54
    FEET_TO_CM: float = 30.48
    GRAMS_TO_KG: float = 1000.0

    # B2B Oversized Cargo constraints
    OVERSIZED_DIMENSION_THRESHOLD: float = 120.0
    OVERSIZED_SURCHARGE_INR: float = 250.0

    # Auxiliary surcharges
    FUEL_SURCHARGE_MULTIPLIER: float = 0.10
    NETWORK_SURCHARGE_INR: float = 25.0
    COD_FEE_MULTIPLIER: float = 0.02
    RTO_CHARGE_MULTIPLIER: float = 0.50  # 50% base freight applied for return legs

    # Service speed premiums
    SURFACE_TRAIN_MULTIPLIER: float = 0.15
    AIR_MULTIPLIER: float = 0.60

    @classmethod
    def _check_serviceability(
        cls, service_type: ServiceType, delivery_pincode: str
    ) -> tuple[bool, str | None]:
        """
        Evaluates route serviceability boundaries based on delivery pin code.
        """
        if service_type == ServiceType.AIR and delivery_pincode.endswith("9"):
            return False, "Air cargo service not available for this remote pin."
            
        if service_type == ServiceType.SURFACE_TRAIN and delivery_pincode.endswith("8"):
            return False, "Rail network not connected to this destination."
            
        return True, None

    @classmethod
    def calculate_bulk_rates(cls, request: BulkRateCalculationRequest) -> BulkRateCalculationResponse:
        """
        Calculates customized bulk rate quotes for a list of requested service/flow combinations.
        """
        specs = request.quotes_to_calculate
        if not specs:
            # Default fallback if quotes_to_calculate is empty or None
            specs = [
                QuoteSpecification(service_type=ServiceType.AIR, is_rto=False),
                QuoteSpecification(service_type=ServiceType.SURFACE_TRAIN, is_rto=False),
                QuoteSpecification(service_type=ServiceType.SURFACE_ROAD, is_rto=False),
            ]

        quotes = []
        for spec in specs:
            serviceable, error_msg = cls._check_serviceability(spec.service_type, request.delivery_pincode)
            
            quote = None
            if serviceable:
                single_req = RateCalculationRequest(
                    pickup_pincode=request.pickup_pincode,
                    delivery_pincode=request.delivery_pincode,
                    packages=request.packages,
                    service_type=spec.service_type,
                    is_cod=request.is_cod,
                    cod_amount=request.cod_amount,
                    shipment_total_value=request.shipment_total_value,
                    shipment_type=request.shipment_type,
                    is_rto=spec.is_rto,
                    is_b2b=getattr(request, 'is_b2b', False)
                )
                quote = cls.calculate_rate(single_req)
            else:
                # Return unserviceable response payload
                quote = RateCalculationResponse(
                    chargeable_weight=0.0,
                    base_charge=0.0,
                    tax_amount=0.0,
                    total_amount=0.0,
                    estimated_days=0,
                    pricing_breakdown={},
                    serviceable=False,
                    error_message=error_msg
                )
                
            quotes.append(ServiceQuote(
                service_type=spec.service_type,
                is_rto=spec.is_rto,
                serviceable=serviceable,
                quote=quote,
                error_message=error_msg
            ))
        return BulkRateCalculationResponse(quotes=quotes)

    @classmethod
    def _normalize_dimensions(
        cls, length: float, breadth: float, height: float, unit: DimensionUnit
    ) -> tuple[float, float, float]:
        """
        Normalizes length, breadth, and height to Centimeters (CM).
        Applies immediate float rounding to 2 decimal places to resolve floating point anomalies.
        """
        if unit == DimensionUnit.M:
            return length * 100.0, breadth * 100.0, height * 100.0
        elif unit == DimensionUnit.IN:
            return (
                round(length * cls.INCH_TO_CM, 2),
                round(breadth * cls.INCH_TO_CM, 2),
                round(height * cls.INCH_TO_CM, 2),
            )
        elif unit == DimensionUnit.FT:
            return (
                round(length * cls.FEET_TO_CM, 2),
                round(breadth * cls.FEET_TO_CM, 2),
                round(height * cls.FEET_TO_CM, 2),
            )
        return length, breadth, height

    @classmethod
    def _normalize_weight(cls, weight: float, unit: WeightUnit) -> float:
        """Normalizes raw weight to Kilograms (KG)."""
        if unit == WeightUnit.G:
            return weight / cls.GRAMS_TO_KG
        return weight

    @classmethod
    def _is_package_oversized(
        cls, length_cm: float, breadth_cm: float, height_cm: float
    ) -> bool:
        """Evaluates if any single normalized package dimension exceeds the carrier threshold."""
        return (
            length_cm > cls.OVERSIZED_DIMENSION_THRESHOLD
            or breadth_cm > cls.OVERSIZED_DIMENSION_THRESHOLD
            or height_cm > cls.OVERSIZED_DIMENSION_THRESHOLD
        )

    @classmethod
    def _calculate_volumetric_weight(
        cls, length_cm: float, breadth_cm: float, height_cm: float, service_type: ServiceType
    ) -> float:
        """Calculates standard volumetric weight in KG based on active carrier speed."""
        divisor = (
            cls.AIR_VOLUMETRIC_DIVISOR
            if service_type == ServiceType.AIR
            else cls.SURFACE_VOLUMETRIC_DIVISOR
        )
        return (length_cm * breadth_cm * height_cm) / divisor

    @classmethod
    def _apply_slab_rounding(cls, weight: float, is_b2b: bool = False) -> float:
        """Applies the minimum weight floor and rounds UP to the nearest 0.5kg billing slab."""
        # Fix: Round to 4 decimal places to eliminate floating point accumulation errors before ceil
        weight = round(weight, 4)
        
        if is_b2b:
            chargeable = max(weight, cls.B2B_MINIMUM_WEIGHT_FLOOR)
            return math.ceil(chargeable * cls.B2B_SLAB_ROUNDING_BASE) / cls.B2B_SLAB_ROUNDING_BASE

        chargeable = max(weight, cls.MINIMUM_WEIGHT_FLOOR)
        return math.ceil(chargeable * cls.SLAB_ROUNDING_BASE) / cls.SLAB_ROUNDING_BASE

    @classmethod
    def calculate_rate(cls, request: RateCalculationRequest) -> RateCalculationResponse:
        """
        Main pricing orchestrator. Calculates freight pricing details, service surcharges,
        taxes, and dynamic ledger breakdowns.
        """
        is_b2b = getattr(request, 'is_b2b', False)

        # 0. Route-based Serviceability check
        serviceable, error_msg = cls._check_serviceability(request.service_type, request.delivery_pincode)
        if not serviceable:
            return RateCalculationResponse(
                chargeable_weight=0.0,
                base_charge=0.0,
                tax_amount=0.0,
                total_amount=0.0,
                estimated_days=0,
                pricing_breakdown={},
                serviceable=False,
                error_message=error_msg
            )

        total_actual_weight = 0.0
        total_volumetric_weight = 0.0
        is_oversized = False

        for pkg in request.packages:
            # 1. Unit Normalization & Conversions
            dim_unit = getattr(pkg, "dimension_unit", DimensionUnit.CM)
            l_cm, b_cm, h_cm = cls._normalize_dimensions(
                pkg.length, pkg.breadth, pkg.height, dim_unit
            )

            # 2. Oversized cargo check
            if cls._is_package_oversized(l_cm, b_cm, h_cm):
                is_oversized = True

            w_unit = getattr(pkg, "weight_unit", WeightUnit.KG)
            w_kg = cls._normalize_weight(pkg.weight, w_unit)

            # 3. Volumetric calculation
            vol_weight_pkg = cls._calculate_volumetric_weight(
                l_cm, b_cm, h_cm, request.service_type
            )

            total_actual_weight += w_kg * pkg.box_count
            total_volumetric_weight += vol_weight_pkg * pkg.box_count

        # 4. Carrier Aggregation & 500g slab rounding
        raw_chargeable_weight = max(total_actual_weight, total_volumetric_weight)
        chargeable_weight = cls._apply_slab_rounding(raw_chargeable_weight, is_b2b=is_b2b)

        # 5. Base transport cost
        base_charge = chargeable_weight * cls.BASE_RATE_PER_KG

        # 6. Resolve service speed premiums
        service_surcharge = 0.0
        estimated_days = 5  # Default road logistics

        if request.service_type == ServiceType.SURFACE_TRAIN:
            service_surcharge = base_charge * cls.SURFACE_TRAIN_MULTIPLIER
            estimated_days = 3
        elif request.service_type == ServiceType.AIR:
            service_surcharge = base_charge * cls.AIR_MULTIPLIER
            estimated_days = 1

        # 7. Dynamic Surcharges
        fuel_surcharge = (base_charge + service_surcharge) * cls.FUEL_SURCHARGE_MULTIPLIER
        network_surcharge = cls.NETWORK_SURCHARGE_INR
        oversized_surcharge = cls.OVERSIZED_SURCHARGE_INR if is_oversized else 0.0

        # COD Remittance operations fee: calculated based on collectible cash cod_amount
        cod_fee = 0.0
        if request.is_cod and request.cod_amount > 0:
            cod_fee = request.cod_amount * cls.COD_FEE_MULTIPLIER

        # Return / RTO Leg surcharge
        rto_surcharge = 0.0
        if request.is_rto or request.shipment_type == ShipmentType.REVERSE:
            rto_surcharge = base_charge * cls.RTO_CHARGE_MULTIPLIER

        docket_charge = cls.B2B_DOCKET_CHARGE_INR if is_b2b else 0.0
        fov_charge = max(request.shipment_total_value * cls.B2B_FOV_PERCENTAGE, cls.B2B_FOV_MINIMUM_INR) if is_b2b and request.shipment_total_value > 0 else 0.0

        # 8. Subtotal & Tax Calculations
        subtotal = (
            base_charge
            + service_surcharge
            + fuel_surcharge
            + network_surcharge
            + oversized_surcharge
            + cod_fee
            + rto_surcharge
            + docket_charge
            + fov_charge
        )
        tax_amount = subtotal * cls.TAX_RATE
        total_amount = subtotal + tax_amount

        # 9. Compile JSON ledger
        pricing_breakdown = {
            "is_oversized": is_oversized,
            "oversized_surcharge": oversized_surcharge,
            "fuel_surcharge": round(fuel_surcharge, 2),
            "network_surcharge": round(network_surcharge, 2),
            "cod_fee": round(cod_fee, 2),
            "rto_surcharge": round(rto_surcharge, 2),
            "base_charge": round(base_charge, 2),
            "service_surcharge": round(service_surcharge, 2),
            "docket_charge": round(docket_charge, 2),
            "fov_charge": round(fov_charge, 2),
            "total_actual_weight": round(total_actual_weight, 2),
            "total_volumetric_weight": round(total_volumetric_weight, 2),
            "raw_chargeable_weight": round(raw_chargeable_weight, 2),
        }

        return RateCalculationResponse(
            chargeable_weight=round(chargeable_weight, 2),
            base_charge=round(base_charge, 2),
            tax_amount=round(tax_amount, 2),
            total_amount=round(total_amount, 2),
            estimated_days=estimated_days,
            pricing_breakdown=pricing_breakdown,
            serviceable=True,
            error_message=None
        )
