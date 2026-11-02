"""
Sell price: what the seller is billed for an option (DESIGN.md v4 §A "Prices", §C.2).

    sell freight = carrier cost × (1 + markup %)        (per cost line, rounded per line)
                   or carrier cost + flat ₹ markup      (FLAT rule: once, on the freight line)
    COD fee      = max(₹min, % × goods COD)             (Logismart's own fee; 0 when COD is off)
    RTO freight  = RTO carrier cost marked up the same way (only once the shipment is in RTO)
    GST          = 18 % × (freight + COD fee + RTO)     (Logismart's GST, frozen at booking)
    total        = freight + COD fee + RTO + GST

Delhivery markup is 0 % (Q1), so the seller pays exactly Delhivery's total. The terms
(markup, COD fee, GST %) are frozen into `payment_details.carrier_cost` at booking, so a
later policy change never re-prices old shipments (A-19).

All arithmetic is Decimal via core/money (Zero Frontend Math: the frontend shows these numbers).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.money import ZERO_MONEY, money_to_float, to_money, to_weight
from app.models.pickups import FreightPaymentMode, ServiceOption
from app.schemas.v1.pricing import PricingPolicy
from app.schemas.v1.tenant_settings import MarkupMode
from app.services import cod_payout
from app.services.pricing.types import CarrierLeg, CarrierQuote, CostLine

GST_PERCENT = Decimal("18")
"""Logismart's GST on freight and fees (C-13: fixed, not a tenant setting)."""
HUNDRED = Decimal("100")
SAC_CODE = "996812"
GST_SPLIT_MODE_ALTERNATIVES = "CGST_SGST_OR_IGST"
PAID_BY_RECEIVER_LABEL = "Receiver (Customer)"
PAID_BY_SENDER_LABEL = "Sender (You)"
PAID_BY_SENDER_WALLET_LABEL = "Sender, billed to wallet"
LINE_COD_FEE = "COD_FEE"
LINE_RTO = "RTO_FREIGHT"
LINE_GST = "GST"
RTO_LINE_LABEL = "Return to origin (RTO) freight"
COD_LINE_LABEL = "COD fee"
OPTION_FREIGHT_LABELS = {
    ServiceOption.DELHIVERY_SURFACE: "Freight (Delhivery Surface)",
    ServiceOption.DELHIVERY_EXPRESS: "Freight (Delhivery Express)",
    ServiceOption.PRIME_SURFACE: "Freight (Logismart Prime)",
    ServiceOption.DELHIVERY_B2B_SURFACE: "Freight (Delhivery B2B Cargo)",
}
FREIGHT_LINE_CODE = "FREIGHT"
RETIRED_ZERO_KEYS = (
    "fuel_surcharge",
    "network_surcharge",
    "oversized_surcharge",
    "service_surcharge",
    "docket_charge",
    "fov_charge",
)
"""Old engine breakdown keys kept at 0 until every screen reads `sell_lines` (DESIGN §C.2)."""
TERMS_KEYS = ("markup_percent", "markup_flat", "cod_fee_percent", "cod_fee_min", "gst_percent")


@dataclass(frozen=True)
class SellTerms:
    """The selling terms frozen at booking (markup is PERCENT, FLAT ₹ per leg, or 0)."""

    markup_percent: Decimal
    cod_fee_percent: Optional[Decimal]
    cod_fee_min: Optional[Decimal]
    gst_percent: Decimal = GST_PERCENT
    markup_flat: Decimal = ZERO_MONEY

    @property
    def cod_enabled(self) -> bool:
        """COD needs both fee values (fail closed)."""
        return self.cod_fee_percent is not None and self.cod_fee_min is not None

    def to_json(self) -> Dict[str, Optional[str]]:
        """JSON-safe form for `carrier_cost["terms"]` (Decimals as strings)."""
        return {name: (None if getattr(self, name) is None else str(getattr(self, name))) for name in TERMS_KEYS}

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "SellTerms":
        """Inverse of `to_json`."""

        def _opt(name: str) -> Optional[Decimal]:
            value = raw.get(name)
            return None if value is None else Decimal(str(value))

        return cls(
            markup_percent=_opt("markup_percent") or Decimal("0"),
            cod_fee_percent=_opt("cod_fee_percent"),
            cod_fee_min=_opt("cod_fee_min"),
            gst_percent=_opt("gst_percent") or GST_PERCENT,
            markup_flat=to_money(_opt("markup_flat") or ZERO_MONEY),
        )


def _markup_rule(quote: CarrierQuote, policy: PricingPolicy) -> Tuple[Decimal, Decimal]:
    """
    (markup %, flat ₹ markup) for an option under the current policy.

    An explicit `option_markups` entry wins (PERCENT or FLAT); otherwise Prime uses the
    lane's own markup and Delhivery options (B2C and B2B) use `delhivery_markup_percent`
    (0 % by default, Q1).
    """
    rule = policy.option_markups.get(quote.option)
    if rule is not None:
        value = Decimal(str(rule.value))
        return (value, ZERO_MONEY) if rule.mode == MarkupMode.PERCENT else (Decimal("0"), to_money(value))
    if quote.option == ServiceOption.PRIME_SURFACE:
        return Decimal(str(quote.markup_percent)), ZERO_MONEY
    return Decimal(str(policy.delhivery_markup_percent)), ZERO_MONEY


def terms_for(quote: CarrierQuote, policy: PricingPolicy) -> SellTerms:
    """
    The selling terms for an option under the current policy (markup rule via
    `_markup_rule`; COD fee only when the policy enables COD and the option carries COD —
    Prime and Delhivery B2B carry no COD at launch, Q9).
    """
    markup_percent, markup_flat = _markup_rule(quote, policy)
    cod_on = policy.cod_enabled and quote.cod_supported
    return SellTerms(
        markup_percent=markup_percent,
        cod_fee_percent=Decimal(str(policy.cod_fee_percent)) if cod_on else None,
        cod_fee_min=Decimal(str(policy.cod_fee_min)) if cod_on else None,
        markup_flat=markup_flat,
    )


@dataclass(frozen=True)
class SellLineValue:
    """One seller-facing line (pre-GST amounts, then the GST line)."""

    code: str
    label: str
    amount: Decimal

    def to_json(self) -> Dict[str, Any]:
        """JSON-safe form for `pricing_breakdown["sell_lines"]`."""
        return {"code": self.code, "label": self.label, "amount": money_to_float(self.amount)}


@dataclass(frozen=True)
class SellPrice:
    """The seller's bill for one option."""

    lines: Tuple[SellLineValue, ...]
    forward_freight: Decimal
    rto_freight: Decimal
    cod_fee: Decimal
    subtotal: Decimal
    gst: Decimal
    total: Decimal


def marked_up(amount: Decimal, markup_percent: Decimal) -> Decimal:
    """`amount × (1 + markup %)`, rounded half-up to the paisa."""
    return to_money(to_money(amount) * (HUNDRED + markup_percent) / HUNDRED)


def cod_fee_for(goods: Decimal, terms: SellTerms) -> Decimal:
    """
    Logismart's COD fee: max(₹min, % × goods COD); 0 when COD is off or there are no goods.

    Args:
        goods: The goods COD the seller typed (A-01; never including shipping).
        terms: The frozen selling terms.

    Returns:
        The pre-GST fee.
    """
    if not terms.cod_enabled or to_money(goods) <= ZERO_MONEY:
        return ZERO_MONEY
    percent_fee = to_money(to_money(goods) * terms.cod_fee_percent / HUNDRED)  # type: ignore[operator]
    return max(percent_fee, to_money(terms.cod_fee_min))


def _forward_lines(option: ServiceOption, leg: CarrierLeg, terms: SellTerms) -> List[SellLineValue]:
    """
    Marked-up forward lines (one freight line for Delhivery; the Prime breakup otherwise).
    A FLAT markup is added once, to the freight line (or the first line when none is FREIGHT).
    """
    lines: Tuple[CostLine, ...] = leg.lines or (
        CostLine(code=FREIGHT_LINE_CODE, label=OPTION_FREIGHT_LABELS[option], amount=leg.cost),
    )
    flat_index = next((i for i, line in enumerate(lines) if line.code == FREIGHT_LINE_CODE), 0)
    return [
        SellLineValue(
            code=line.code,
            label=OPTION_FREIGHT_LABELS[option] if line.code == FREIGHT_LINE_CODE else line.label,
            amount=to_money(
                marked_up(line.amount, terms.markup_percent) + (terms.markup_flat if index == flat_index else ZERO_MONEY)
            ),
        )
        for index, line in enumerate(lines)
    ]


def _rto_freight(rto: Optional[CarrierLeg], terms: SellTerms, include_rto: bool) -> Decimal:
    """Marked-up RTO freight (same markup rule as the forward leg); 0 when not billed."""
    if not include_rto or rto is None:
        return ZERO_MONEY
    return to_money(marked_up(rto.cost, terms.markup_percent) + terms.markup_flat)


def compute_sell(
    option: ServiceOption,
    forward: CarrierLeg,
    rto: Optional[CarrierLeg],
    terms: SellTerms,
    *,
    cod_goods: Decimal,
    include_rto: bool,
    charge_cod_fee: bool = True,
) -> SellPrice:
    """
    The seller's bill.

    Args:
        option: The service option (line labels).
        forward: Forward (or reverse) carrier leg.
        rto: RTO carrier leg (required when `include_rto`).
        terms: Frozen selling terms.
        cod_goods: Goods COD (0 when not COD).
        include_rto: Bill the RTO leg (shipment is in an RTO status).
        charge_cod_fee: False once no cash is collected (RTO / waived).

    Returns:
        The SellPrice (every amount rounded to the paisa; total == subtotal + GST).
    """
    lines = _forward_lines(option, forward, terms)
    forward_freight = to_money(sum((line.amount for line in lines), ZERO_MONEY))
    rto_freight = _rto_freight(rto, terms, include_rto)
    if rto_freight > ZERO_MONEY:
        lines.append(SellLineValue(code=LINE_RTO, label=RTO_LINE_LABEL, amount=rto_freight))
    cod_fee = cod_fee_for(cod_goods, terms) if charge_cod_fee else ZERO_MONEY
    if cod_fee > ZERO_MONEY:
        lines.append(SellLineValue(code=LINE_COD_FEE, label=COD_LINE_LABEL, amount=cod_fee))
    subtotal = to_money(forward_freight + rto_freight + cod_fee)
    gst = to_money(subtotal * terms.gst_percent / HUNDRED)
    lines.append(SellLineValue(code=LINE_GST, label=f"GST ({terms.gst_percent.normalize()}%)", amount=gst))
    return SellPrice(
        lines=tuple(lines),
        forward_freight=forward_freight,
        rto_freight=rto_freight,
        cod_fee=cod_fee,
        subtotal=subtotal,
        gst=gst,
        total=to_money(subtotal + gst),
    )


def shipping_paid_by(mode: FreightPaymentMode) -> str:
    """Display label of who pays the freight (never changes a number)."""
    if mode == FreightPaymentMode.TO_PAY:
        return PAID_BY_RECEIVER_LABEL
    if mode == FreightPaymentMode.POSTPAID:
        return PAID_BY_SENDER_WALLET_LABEL
    return PAID_BY_SENDER_LABEL


def door_and_remittance(
    *, total: Decimal, mode: FreightPaymentMode, is_cod: bool, cod_goods: Decimal, add_shipping_to_cod: bool
) -> Tuple[Decimal, Decimal]:
    """
    (cash the rider collects, COD paid back to the seller), via `cod_payout` only.

    A-01: the goods COD is what the seller typed; shipping is added on top when asked.
    """
    cod_amount, freight_collectible = cod_payout.collectible_amounts(
        is_cod=is_cod,
        goods=to_money(cod_goods),
        total=to_money(total),
        mode=mode,
        add_shipping_to_cod=add_shipping_to_cod,
        merchant_paid=ZERO_MONEY,
    )
    remittance = to_money(cod_goods) if is_cod else ZERO_MONEY
    return to_money(cod_amount + freight_collectible), remittance


@dataclass(frozen=True)
class BreakdownContext:
    """Display facts that go into the customer `pricing_breakdown` next to the money."""

    option: ServiceOption
    leg: str
    transit_days: Optional[int]
    priced_from_cache: bool
    actual_weight_kg: Decimal
    volumetric_weight_kg: Decimal
    chargeable_weight_kg: Decimal
    mode: FreightPaymentMode
    is_cod: bool
    cod_goods: Decimal
    add_shipping_to_cod: bool


def customer_breakdown(sell: SellPrice, ctx: BreakdownContext) -> Dict[str, Any]:
    """
    The customer-visible `pricing_breakdown` (JSON-safe). Never contains carrier cost,
    gross, markup or transporter data.

    Invariant: base_charge + cod_fee + rto_surcharge + gst_total == total.
    """
    gst = sell.gst
    cgst = to_money(gst / 2)
    door, remittance = door_and_remittance(
        total=sell.total,
        mode=ctx.mode,
        is_cod=ctx.is_cod,
        cod_goods=ctx.cod_goods,
        add_shipping_to_cod=ctx.add_shipping_to_cod,
    )
    breakdown: Dict[str, Any] = {
        "sac_code": SAC_CODE,
        "gst_total": money_to_float(gst),
        "gst_split_mode": GST_SPLIT_MODE_ALTERNATIVES,
        "cgst_amount": money_to_float(cgst),
        "sgst_amount": money_to_float(to_money(gst - cgst)),
        "igst_amount": money_to_float(gst),
        "is_oversized": False,
        "cod_fee": money_to_float(sell.cod_fee),
        "rto_surcharge": money_to_float(sell.rto_freight),
        "base_charge": money_to_float(sell.forward_freight),
        "total_actual_weight": float(to_weight(ctx.actual_weight_kg)),
        "total_volumetric_weight": float(to_weight(ctx.volumetric_weight_kg)),
        "raw_chargeable_weight": float(to_weight(ctx.chargeable_weight_kg)),
        "subtotal": money_to_float(sell.subtotal),
        "total_customer_pays": money_to_float(door),
        "sender_net_remittance": money_to_float(remittance),
        "shipping_paid_by": shipping_paid_by(ctx.mode),
        "service_option": ctx.option.value,
        "leg": ctx.leg,
        "transit_days": ctx.transit_days,
        "sell_lines": [line.to_json() for line in sell.lines],
        "priced_from_cache": ctx.priced_from_cache,
    }
    breakdown.update({key: 0.0 for key in RETIRED_ZERO_KEYS})
    return breakdown
