"""
Deterministic fake of the Delhivery B2B (LTL) API for the golden test tenant only
(staging Delhivery B2B has no pricing file, so tests can't use it).

Formula (pre-GST, rupees), mirroring a typical Delhivery B2B contract:
- chargeable kg = max(actual kg, Σ L×W×H×count / 4500, 20 kg)
- freight = chargeable kg × ₹9; fuel = 10 % of freight; docket ₹100
- ROV (carrier's risk) = max(0.1 % × invoice, ₹100); owner's risk → 0
- pre-tax = max(sum, ₹400 minimum LR); GST 18 %; `total` = pre-tax + GST
TAT = 4 days. The answer shape matches what `delhivery_b2b.estimate_amounts` reads.

Test knobs (module attributes, read at call time so tests can monkeypatch them):
`FAKE_B2B_DOWN`, `FAKE_B2B_PRE_TAX_OVERRIDE`, `FAKE_B2B_UNSERVICEABLE_PINS`.
The fake refuses any tenant outside `FAKE_PROVIDER_TENANT_SLUGS`.
"""

from decimal import Decimal
from typing import Any, Dict, FrozenSet, Mapping, Optional

from app.core.money import ZERO_MONEY, money_to_float, to_money
from app.services.pricing.delhivery_client import DelhiveryRefusedError, DelhiveryUnavailableError
from app.services.pricing.fake_delhivery import FAKE_PROVIDER_TENANT_SLUGS

FAKE_B2B_DOWN = False
"""True → every call raises DelhiveryUnavailableError (timeout / login refused simulation)."""
FAKE_B2B_PRE_TAX_OVERRIDE: Optional[Decimal] = None
"""When set, the pre-tax amount of every estimate (409 tests)."""
FAKE_B2B_UNSERVICEABLE_PINS: FrozenSet[str] = frozenset({"999999"})

RATE_PER_KG = Decimal("9")
FUEL_PERCENT = Decimal("10")
DOCKET_CHARGE = Decimal("100")
ROV_PERCENT = Decimal("0.1")
ROV_MINIMUM = Decimal("100")
MIN_LR_CHARGE = Decimal("400")
MIN_CHARGEABLE_KG = Decimal("20")
VOLUMETRIC_DIVISOR = Decimal("4500")
GST_PERCENT = Decimal("18")
HUNDRED = Decimal("100")
GRAMS_PER_KG = Decimal("1000")
FAKE_TAT_DAYS = 4


def _chargeable_kg(body: Mapping[str, Any]) -> Decimal:
    """max(actual, volumetric at /4500, 20 kg) from an estimate body."""
    actual = Decimal(str(body.get("weight_g") or 0)) / GRAMS_PER_KG
    volume = sum(
        (
            Decimal(str(box["length_cm"])) * Decimal(str(box["width_cm"])) * Decimal(str(box["height_cm"]))
            * Decimal(str(box["box_count"]))
            for box in body.get("dimensions") or []
        ),
        Decimal("0"),
    )
    return max(actual, volume / VOLUMETRIC_DIVISOR, MIN_CHARGEABLE_KG).quantize(Decimal("0.001"))


def _breakup(body: Mapping[str, Any]) -> Dict[str, Decimal]:
    """The pre-GST lines of one estimate."""
    freight = to_money(_chargeable_kg(body) * RATE_PER_KG)
    rov = (
        max(to_money(Decimal(str(body.get("inv_amount") or 0)) * ROV_PERCENT / HUNDRED), ROV_MINIMUM)
        if body.get("rov_insurance")
        else ZERO_MONEY
    )
    lines = {
        "base_freight_charge": freight,
        "fuel_surcharge": to_money(freight * FUEL_PERCENT / HUNDRED),
        "docket_charge": DOCKET_CHARGE,
        "rov_charge": rov,
    }
    subtotal = to_money(sum(lines.values(), ZERO_MONEY))
    lines["min_lr_topup"] = max(to_money(MIN_LR_CHARGE - subtotal), ZERO_MONEY)
    return lines


class FakeDelhiveryB2BApi:
    """Same interface as `LiveDelhiveryB2BApi`, answered from the formula above."""

    def __init__(self, tenant_slug: str) -> None:
        if tenant_slug not in FAKE_PROVIDER_TENANT_SLUGS:
            raise PermissionError(f"The fake Delhivery B2B provider never serves tenant '{tenant_slug}'.")

    @staticmethod
    def _check_up() -> None:
        """Raises when the test switched the fake 'down'."""
        if FAKE_B2B_DOWN:
            raise DelhiveryUnavailableError("Fake Delhivery B2B is down.")

    async def estimate(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """A Delhivery-B2B-shaped estimate answer."""
        self._check_up()
        for key in ("source_pin", "consignee_pin"):
            if str(body[key]) in FAKE_B2B_UNSERVICEABLE_PINS:
                raise DelhiveryRefusedError(f"pin : {body[key]} not found in DataBase")
        lines = _breakup(body)
        pre_tax = to_money(sum(lines.values(), ZERO_MONEY))
        if FAKE_B2B_PRE_TAX_OVERRIDE is not None:
            pre_tax = to_money(Decimal(str(FAKE_B2B_PRE_TAX_OVERRIDE)))
        gst = to_money(pre_tax * GST_PERCENT / HUNDRED)
        breakup: Dict[str, Any] = {key: money_to_float(value) for key, value in lines.items()}
        breakup.update({"pre_tax_freight_charges": money_to_float(pre_tax), "gst": money_to_float(gst)})
        return {
            "success": True,
            "data": {
                "total": money_to_float(to_money(pre_tax + gst)),
                "chargeable_weight_kg": float(_chargeable_kg(body)),
                "price_breakup": breakup,
            },
        }

    async def pincode_serviceable(self, pincode: str, weight_g: int) -> bool:
        """Every pin is served except the configured unserviceable ones."""
        self._check_up()
        return pincode not in FAKE_B2B_UNSERVICEABLE_PINS

    async def tat_days(self, origin_pin: str, destination_pin: str) -> Optional[int]:
        """Fixed transit days."""
        self._check_up()
        return FAKE_TAT_DAYS
