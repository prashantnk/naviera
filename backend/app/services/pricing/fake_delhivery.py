"""
Deterministic fake of the Delhivery B2C API for the golden test tenant only
(DESIGN.md v4 §C.2 "fake provider"; staging Delhivery returns ₹0 prices).

The price formula reproduces the pre-redesign static numbers so money tests keep their
constants (board #348): slab = cgm rounded up to 500 g (min 500 g);
- `ss=Delivered`: gross = slab_kg × 50 × (1.6 for md=E) × 1.10 + 25
- `ss=RTO`: gross = Delivered gross + slab_kg × 25 (cumulative, like real Delhivery; the
  provider subtracts the forward leg, so the return-only leg stays slab_kg × 25)
- `ss=DTO`: Delivered gross + slab_kg × 25
`total_amount` = gross × 1.18, `charge_COD` = 0 (Logismart charges its own COD fee).

Test knobs (module attributes, read at call time so tests can monkeypatch them):
`FAKE_DELHIVERY_DOWN`, `FAKE_GROSS_OVERRIDE`, `FAKE_UNSERVICEABLE_PINS`,
`FAKE_EMBARGO_PINS`, `FAKE_ODA_PINS`, plus the optional overrides fixture
`fixtures/fake_delhivery_rates.json` keyed "o_pin-d_pin-md-ss-slab_grams" → gross.
Binding is env-driven: only tenants in `DELHIVERY_FAKE_TENANT_SLUGS` (set by the test harness,
never on a deployment) get the fake. As a second guard the fake itself refuses any tenant outside
`FAKE_PROVIDER_TENANT_SLUGS`, so a misconfigured env can never price a live tenant on it.
"""

import json
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, Mapping, Optional

from app.core.money import to_money
from app.services.pricing.delhivery_client import (
    DelhiveryRefusedError,
    DelhiveryUnavailableError,
)

FAKE_PROVIDER_TENANT_SLUGS: FrozenSet[str] = frozenset({"logismart-test"})
"""Mirror of `scripts/tenant_data_core.ALLOWED_TEST_SLUGS`: the only tenants the fake may ever serve
(a safety allow-list; which tenants actually use it is `DELHIVERY_FAKE_TENANT_SLUGS`)."""

FAKE_DELHIVERY_DOWN = False
"""True → every call raises DelhiveryUnavailableError (timeout/throttle simulation)."""
FAKE_GROSS_OVERRIDE: Optional[Decimal] = None
"""When set, the forward (`Delivered` / `DTO`) gross of every price call (409 tests)."""
FAKE_UNSERVICEABLE_PINS: FrozenSet[str] = frozenset({"999999"})
FAKE_EMBARGO_PINS: FrozenSet[str] = frozenset()
FAKE_ODA_PINS: FrozenSet[str] = frozenset()

SLAB_GRAMS = 500
BASE_RATE_PER_KG = Decimal("50")
EXPRESS_MULTIPLIER = Decimal("1.6")
FUEL_MULTIPLIER = Decimal("1.10")
NETWORK_CHARGE = Decimal("25")
RETURN_RATE_PER_KG = Decimal("25")
GST_MULTIPLIER = Decimal("1.18")
FAKE_ZONE = "C"
FAKE_TRANSIT_DAYS = {"S": 5, "E": 2}
OVERRIDES_PATH = Path(__file__).parent / "fixtures" / "fake_delhivery_rates.json"


@lru_cache(maxsize=1)
def _overrides() -> Dict[str, str]:
    """The optional gross overrides fixture (empty when the file is absent)."""
    if not OVERRIDES_PATH.exists():
        return {}
    return {str(k): str(v) for k, v in json.loads(OVERRIDES_PATH.read_text()).items()}


def _slab_grams(cgm: int) -> int:
    """cgm rounded up to the 500 g slab, never below one slab."""
    return max(SLAB_GRAMS, math.ceil(int(cgm) / SLAB_GRAMS) * SLAB_GRAMS)


def _formula_gross(md: str, ss: str, slab_kg: Decimal) -> Decimal:
    """The pre-redesign static formula for one leg."""
    base = slab_kg * BASE_RATE_PER_KG * (EXPRESS_MULTIPLIER if md == "E" else Decimal("1"))
    delivered = base * FUEL_MULTIPLIER + NETWORK_CHARGE
    if ss == "RTO":
        return delivered + slab_kg * RETURN_RATE_PER_KG
    if ss == "DTO":
        return delivered + slab_kg * RETURN_RATE_PER_KG
    return delivered


class FakeDelhiveryApi:
    """Same interface as `LiveDelhiveryApi`, answered from the formula / fixture."""

    def __init__(self, tenant_slug: str) -> None:
        if tenant_slug not in FAKE_PROVIDER_TENANT_SLUGS:
            raise PermissionError(f"The fake Delhivery provider never serves tenant '{tenant_slug}'.")

    @staticmethod
    def _check_up() -> None:
        """Raises when the test switched the fake 'down'."""
        if FAKE_DELHIVERY_DOWN:
            raise DelhiveryUnavailableError("Fake Delhivery is down.")

    async def invoice_charges(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        """A Delhivery-shaped price answer."""
        self._check_up()
        o_pin, d_pin = str(params["o_pin"]), str(params["d_pin"])
        if o_pin in FAKE_UNSERVICEABLE_PINS:
            raise DelhiveryRefusedError("Unable to process request for provided o_pin")
        if d_pin in FAKE_UNSERVICEABLE_PINS:
            raise DelhiveryRefusedError("Unable to process request, Please contact: lastmile-integration@delhivery.com")
        md, ss = str(params["md"]), str(params["ss"])
        slab = _slab_grams(int(params["cgm"]))
        slab_kg = Decimal(slab) / Decimal(1000)
        override = _overrides().get(f"{o_pin}-{d_pin}-{md}-{ss}-{slab}")
        gross = Decimal(override) if override is not None else _formula_gross(md, ss, slab_kg)
        if FAKE_GROSS_OVERRIDE is not None:
            forward = Decimal(str(FAKE_GROSS_OVERRIDE))
            gross = forward + slab_kg * RETURN_RATE_PER_KG if ss == "RTO" else forward
        gross = to_money(gross)
        tax = to_money(gross * (GST_MULTIPLIER - 1))
        return {
            "gross_amount": float(gross),
            "total_amount": float(to_money(gross + tax)),
            "charged_weight": slab,
            "zone": FAKE_ZONE,
            "divisor": 5000,
            "charge_DL": float(gross),
            "charge_COD": 0.0,
            "tax_data": {"IGST": float(tax), "CGST": 0.0, "SGST": 0.0},
        }

    async def pincode(self, pincode: str) -> Optional[Dict[str, Any]]:
        """Every valid pin is served except the configured unserviceable ones."""
        self._check_up()
        if pincode in FAKE_UNSERVICEABLE_PINS:
            return None
        return {
            "pin": int(pincode),
            "pre_paid": "Y",
            "cod": "Y",
            "pickup": "Y",
            "repl": "Y",
            "is_oda": "Y" if pincode in FAKE_ODA_PINS else "N",
            "remarks": "Embargo" if pincode in FAKE_EMBARGO_PINS else "",
        }

    async def expected_tat(self, origin_pin: str, destination_pin: str, mot: str) -> Optional[int]:
        """Fixed transit days per mode."""
        self._check_up()
        return FAKE_TRANSIT_DAYS.get(mot)
