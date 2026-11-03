"""
Randomized money-property test for re-pricing (ship-readiness plan Phase B, "Tests").

A seeded Hypothesis strategy draws whole shipment lives: a payment mode (PREPAID,
customer POSTPAID, TO_PAY), COD on or off, up to two merchant edits while Ready to
ship, a dispatch, and then up to four post-pickup events in random order: hub
measurement, NDR additional charge, weight claim, RTO, and an admin cancel (which
converts to RTO after pickup). After EVERY step it checks, straight from PostgreSQL:

- refunds never exceed bill debits (H-1);
- GST register (INVOICE + DEBIT_NOTE - CREDIT_NOTE, separate charges excluded) == net
  debited, and == the bill for a wallet-billed shipment;
- the merchant wallet balance == its COMPLETED ledger sum;
- the bill == the pricing engine's price for the current billing basis (the formula
  is treated as correct; the oracle replays it with the frozen test rate card);
- the stored collectibles follow plan B7 (TO_PAY: freight in `freight_collectible`,
  never inside `cod_amount`).

It runs against the guarded `logismart-test` tenant only (no reset here: it books its
own shipments and asserts deltas), so it is safe to run after the golden suites.

Spring analogy: a jqwik `@Property` test with a fixed seed, driving MockMvc.
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional

import pytest
from golden_journeys.golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GoldenEnvError,
    acquire_run_lock,
    headers,
    load_accounts,
    load_settings_fixture,
    load_test_tenant,
    release_run_lock,
)
from golden_journeys.test_suite_9_repricing import (
    M,
    _action,
    _b2c_warehouse,
    _book_b2c_2kg,
    _client,
    _dispatch,
    _get,
    _measure,
    _patch,
    _raise_exception,
    _std_package_patch,
    assert_money_invariants,
)
from hypothesis import HealthCheck, Phase, example, given, seed, settings
from hypothesis import strategies as st

from app.models.delhivery_modules import WeightDisputeClaimStatus
from app.models.pickups import (
    FreightPaymentMode,
    NdrAction,
    NdrExceptionReason,
    PickupStatus,
)
from app.schemas.v1.pricing import PricingPolicy
from app.services.pricing.fake_delhivery import _formula_gross, _slab_grams
from app.services.pricing.sell_price import SellTerms, cod_fee_for, marked_up

# --- Strategy constants --------------------------------------------------------

PROPERTY_SEED = 20261027
"""Fixed seed: every run draws the same lives, so a failure is reproducible."""
MAX_EXAMPLES = int(os.getenv("PROPERTY_MAX_EXAMPLES", "6"))
GOODS_VALUE = 1000.0
DECLARED_WEIGHT_KG = 2.0
CLAIMED_WEIGHT_G = 2000.0
NDR_CHARGE_EXCL_GST = 100.0
WEIGHTS_KG = (1.0, 3.5, 5.0)
MODES = (FreightPaymentMode.PREPAID, FreightPaymentMode.POSTPAID, FreightPaymentMode.TO_PAY)
PICKUP_PINCODE = "122001"
DROP_PINCODE = "110001"
CLAIM_STATUS_NONE = WeightDisputeClaimStatus.NONE.value
CLAIM_ACCEPTED = WeightDisputeClaimStatus.ACCEPTED.value

MEASURABLE_STATUSES = frozenset({PickupStatus.IN_TRANSIT, PickupStatus.RTO_INITIATED})

OPERATION = st.one_of(
    st.tuples(st.just("measure"), st.sampled_from(WEIGHTS_KG)),
    st.just(("ndr_charge",)),
    st.just(("claim",)),
    st.just(("rto",)),
    st.just(("cancel",)),
)
LIFE = st.fixed_dictionaries(
    {
        "mode": st.sampled_from(MODES),
        "cod": st.booleans(),
        "pre_edits": st.lists(st.sampled_from(WEIGHTS_KG), max_size=2),
        "post_ops": st.lists(OPERATION, min_size=1, max_size=4),
    }
)


# --- Fixtures: real JWTs on the guarded test tenant, no mocked app ---------------


@pytest.fixture
async def db_session() -> AsyncIterator[None]:
    """Shadows the parent rollback-session fixture: this module commits through the API."""
    yield None


@pytest.fixture(autouse=True)
async def global_dependency_overrides() -> AsyncIterator[None]:
    """Shadows the parent mocked-auth overrides: real tokens only."""
    yield


@pytest.fixture(autouse=True, scope="module")
async def money_tenant_guard() -> AsyncIterator[None]:
    """Slug + environment guard and the run lock; skips cleanly before the seed."""
    try:
        await load_test_tenant()
    except GoldenEnvError as exc:
        pytest.skip(str(exc))
    handle = acquire_run_lock()
    try:
        yield
    finally:
        release_run_lock(handle)


# --- The model (what the bill should be) ------------------------------------------


@dataclass
class LifeModel:
    """Expected billing inputs of one shipment, updated by each successful step."""

    mode: FreightPaymentMode
    cod: bool
    weight_kg: float = DECLARED_WEIGHT_KG
    is_rto: bool = False
    claimed: bool = False
    log: List[str] = field(default_factory=list)


def _policy() -> PricingPolicy:
    """The frozen pricing_policy of logismart-test."""
    return PricingPolicy.model_validate(load_settings_fixture().get("pricing_policy") or {})


def engine_total(model: LifeModel, *, cod_fee: bool = True) -> Decimal:
    """Oracle: the engine's price for the model's current billing basis on Delhivery Surface."""
    policy = _policy()
    markup = Decimal(str(policy.delhivery_markup_percent))
    terms = SellTerms(
        markup_percent=markup,
        cod_fee_percent=Decimal(str(policy.cod_fee_percent)) if policy.cod_fee_percent is not None else None,
        cod_fee_min=Decimal(str(policy.cod_fee_min)) if policy.cod_fee_min is not None else None,
    )
    slab_kg = Decimal(_slab_grams(int(Decimal(str(model.weight_kg)) * 1000))) / Decimal(1000)
    fwd = marked_up(_formula_gross("S", "Delivered", slab_kg), markup)
    rto = (
        # Delhivery's ss=RTO is cumulative; the billed RTO leg is the return-only part.
        marked_up(_formula_gross("S", "RTO", slab_kg) - _formula_gross("S", "Delivered", slab_kg), markup)
        if model.is_rto
        else Decimal("0.00")
    )
    cod = (
        cod_fee_for(M(GOODS_VALUE), terms)
        if (model.cod and cod_fee)
        else Decimal("0.00")
    )
    subtotal = fwd + rto + cod
    gst = M(subtotal * Decimal("0.18"))
    return M(subtotal + gst)


def acceptable_totals(model: LifeModel) -> List[Decimal]:
    """
    Allowed bills for the model. An RTO of a COD parcel may or may not carry the COD
    fee: wave 1 keeps it, wave 2 (plan C2, D50) reverses it with a CREDIT_NOTE.
    """
    if model.is_rto and model.cod:
        return [engine_total(model), engine_total(model, cod_fee=False)]
    return [engine_total(model)]


async def assert_life_consistent(sid: str, model: LifeModel) -> None:
    """All Phase B invariants plus the engine oracle and the B7 collectible rule."""
    snap = await assert_money_invariants(sid)
    allowed = acceptable_totals(model)
    assert snap.total in allowed, f"bill {snap.total} not in {allowed}; steps: {model.log}"
    if model.is_rto or snap.shipment.status == PickupStatus.COMPLETED:
        return
    goods_cod = M(GOODS_VALUE) if model.cod else M(0)
    assert M(snap.payment.cod_amount) == goods_cod, f"cod_amount; steps: {model.log}"
    if model.mode == FreightPaymentMode.TO_PAY:
        assert M(snap.payment.freight_collectible) == snap.total, f"TO_PAY collectible; steps: {model.log}"
    else:
        assert M(snap.payment.freight_collectible) == M(0)


# --- Steps -----------------------------------------------------------------------


async def _status(client: Any, accounts: Mapping[str, Any], sid: str) -> PickupStatus:
    return PickupStatus((await _get(client, accounts, sid))["status"])


async def step_measure(client: Any, accounts: Mapping[str, Any], sid: str, model: LifeModel, weight: float) -> None:
    """Hub weight-only measurement (declared box kept, weight scaled)."""
    if await _status(client, accounts, sid) not in MEASURABLE_STATUSES:
        return
    resp = await _measure(client, accounts, sid, weight_kg=weight, remark="property measure")
    assert resp.status_code == 200, resp.text
    model.weight_kg = weight
    model.log.append(f"measure {weight}")


async def step_ndr_charge(client: Any, accounts: Mapping[str, Any], sid: str, model: LifeModel) -> None:
    """Mathadi Rs.100 (GST-exclusive) raised by ops and acknowledged by the merchant."""
    if await _status(client, accounts, sid) != PickupStatus.IN_TRANSIT:
        return
    await _raise_exception(
        client, accounts, sid, NdrExceptionReason.ADDITIONAL_CHARGES, charge_amount=NDR_CHARGE_EXCL_GST
    )
    await _action(client, accounts, sid, CUSTOMER_B2C_EMAIL, {"action": NdrAction.ACKNOWLEDGE_CHARGES.value})
    model.log.append("ndr_charge")


async def _open_dispute(client: Any, accounts: Mapping[str, Any], awb: str) -> Optional[Dict[str, Any]]:
    resp = await client.get(
        f"/api/v1/disputes/weight-mismatch?search={awb}", headers=headers(accounts, CUSTOMER_B2C_EMAIL)
    )
    assert resp.status_code == 200, resp.text
    rows = [
        r
        for r in resp.json()
        if r.get("claim_status") == CLAIM_STATUS_NONE and float(r.get("cost_diff_inr") or 0.0) > 0
    ]
    return rows[0] if rows else None


async def step_claim(client: Any, accounts: Mapping[str, Any], sid: str, awb: str, model: LifeModel) -> None:
    """Merchant claims the declared 2 kg; the admin accepts; the bill returns to the manifested weight (A-07)."""
    if model.claimed:
        return
    dispute = await _open_dispute(client, accounts, awb)
    if dispute is None:
        return
    raised = await client.post(
        "/api/v1/disputes/weight-mismatch/claims",
        headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        json={"tracking_ids": [awb], "claimed_weight_g": CLAIMED_WEIGHT_G, "claim_remarks": "property claim"},
    )
    assert raised.status_code == 200, raised.text
    accepted = await client.patch(
        f"/api/v1/disputes/weight-mismatch/{dispute['id']}/resolve",
        headers=headers(accounts, ADMIN_EMAIL),
        json={"claim_status": CLAIM_ACCEPTED, "claim_remarks": "property accept"},
    )
    assert accepted.status_code == 200, accepted.text
    manifested_g = float(dispute.get("manifested_weight_g") or CLAIMED_WEIGHT_G)
    model.weight_kg = max(CLAIMED_WEIGHT_G, manifested_g) / 1000.0
    model.claimed = True
    model.log.append("claim")


async def step_rto(client: Any, accounts: Mapping[str, Any], sid: str, model: LifeModel) -> None:
    """Admin moves an in-transit parcel to RTO (billed once; A-22 restricts manual RTO to Owner/Admin)."""
    if await _status(client, accounts, sid) != PickupStatus.IN_TRANSIT:
        return
    resp = await _patch(client, accounts, sid, ADMIN_EMAIL, {"status": PickupStatus.RTO_INITIATED.value})
    assert resp.status_code == 200, resp.text
    model.is_rto = True
    model.log.append("rto")


async def step_cancel(client: Any, accounts: Mapping[str, Any], sid: str, model: LifeModel) -> None:
    """Admin cancel after pickup converts to RTO (plan B10, never a refund)."""
    if await _status(client, accounts, sid) != PickupStatus.IN_TRANSIT:
        return
    resp = await client.post(f"/api/v1/shipments/{sid}/cancel", headers=headers(accounts, ADMIN_EMAIL))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == PickupStatus.RTO_INITIATED.value
    model.is_rto = True
    model.log.append("cancel->rto")


# --- The property ----------------------------------------------------------------


@pytest.mark.asyncio
@seed(PROPERTY_SEED)
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    database=None,
    phases=[Phase.explicit, Phase.generate],
    suppress_health_check=list(HealthCheck),
)
@example(
    life={
        "mode": FreightPaymentMode.PREPAID,
        "cod": True,
        "pre_edits": [3.5],
        "post_ops": [("measure", 5.0), ("ndr_charge",), ("claim",), ("cancel",)],
    }
)
@example(
    life={
        "mode": FreightPaymentMode.TO_PAY,
        "cod": True,
        "pre_edits": [],
        "post_ops": [("measure", 3.5), ("rto",), ("measure", 5.0)],
    }
)
@given(life=LIFE)
async def test_money_invariants_hold_after_every_step(life: Dict[str, Any]) -> None:
    accounts = await load_accounts()
    model = LifeModel(mode=life["mode"], cod=life["cod"])
    async with _client() as client:
        booked = await _book_b2c_2kg(
            client, accounts, f"PROP-{model.mode.value}", mode=model.mode,
            goods=GOODS_VALUE, is_cod=model.cod,
        )
        sid, awb = booked["id"], booked["tracking_id"]
        model.log.append(f"book {model.mode.value} cod={model.cod}")
        await assert_life_consistent(sid, model)

        current = booked
        for weight in life["pre_edits"]:
            resp = await _patch(
                client, accounts, sid, CUSTOMER_B2C_EMAIL,
                {"comment": "property pre-pickup edit", "packages": _std_package_patch(current, weight)},
            )
            assert resp.status_code == 200, resp.text
            current = resp.json()
            model.weight_kg = weight
            model.log.append(f"edit {weight}")
            await assert_life_consistent(sid, model)

        warehouse_id = await _b2c_warehouse(client, accounts)
        await _dispatch(client, accounts, CUSTOMER_B2C_EMAIL, warehouse_id, [sid])
        model.log.append("dispatch")
        await assert_life_consistent(sid, model)

        for op in life["post_ops"]:
            name = op[0]
            if name == "measure":
                await step_measure(client, accounts, sid, model, op[1])
            elif name == "ndr_charge":
                await step_ndr_charge(client, accounts, sid, model)
            elif name == "claim":
                await step_claim(client, accounts, sid, awb, model)
            elif name == "rto":
                await step_rto(client, accounts, sid, model)
            elif name == "cancel":
                await step_cancel(client, accounts, sid, model)
            await assert_life_consistent(sid, model)
