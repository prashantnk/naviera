"""
The staff-only selling policy (`tenant.settings["pricing_policy"]`, DESIGN.md v4 §C.2).

- Missing policy → defaults (Delhivery markup 0 %, Prime 20 %, standard COD fee 2 % / min ₹20, all options on).
- Invalid stored policy → `None`, and every option is shown as unavailable (fail closed).
- COD is ON when BOTH the COD fee minimum and percentage are non-null (admin can clear both to turn COD off).

Pure reads (no settings writes) so quoting and re-pricing can import it without cycles;
the staff editor lives in `policy_admin.py`.

Spring analogy: a reader of a typed `@ConfigurationProperties` block on the tenant row.
"""

import logging
from typing import Optional

from pydantic import ValidationError

from app.models.tenants import Tenant
from app.schemas.v1.pricing import PricingPolicy, PricingPolicyRead
from app.services.pricing.delhivery_b2b_client import live_b2b_api_if_configured
from app.services.pricing.delhivery_client import is_fake_tenant, live_api_if_configured

logger = logging.getLogger(__name__)

PRICING_POLICY_SETTINGS_KEY = "pricing_policy"
COD_DISABLED_DETAIL = (
    "Cash on Delivery is not enabled yet. Book this shipment as Prepaid, or ask Logismart "
    "to switch COD on."
)
"""400 detail when a booking asks for COD while the COD fee is not set (fail closed)."""
COD_DISABLED_REASON = "COD is not enabled yet. Ask Logismart to switch it on."
POLICY_INVALID_REASON = "Pricing is not set up correctly yet. Please contact Logismart support."


def policy_of(tenant: Tenant) -> Optional[PricingPolicy]:
    """
    The tenant's selling policy.

    Args:
        tenant: The tenant row (settings JSON).

    Returns:
        The validated policy; defaults when unset; None when the stored value is invalid.
    """
    raw = (tenant.settings or {}).get(PRICING_POLICY_SETTINGS_KEY)
    if raw is None:
        return PricingPolicy()
    try:
        return PricingPolicy.model_validate(raw)
    except ValidationError:
        logger.error("Invalid pricing_policy for tenant %s; all options unavailable.", tenant.id)
        return None


def delhivery_configured(tenant: Tenant) -> bool:
    """True when Delhivery prices can be fetched for this tenant (live token or the test fake)."""
    if is_fake_tenant(tenant.slug):
        return True
    return live_api_if_configured(str(tenant.id), tenant.slug) is not None


def delhivery_b2b_configured(tenant: Tenant) -> bool:
    """True when Delhivery B2B estimates can be fetched for this tenant (live login, B2C fallback, or test fake)."""
    if is_fake_tenant(tenant.slug):
        return True
    tid = str(tenant.id)
    return (
        live_b2b_api_if_configured(tid, tenant.slug) is not None
        or live_api_if_configured(tid, tenant.slug) is not None
    )


def to_read(tenant: Tenant, policy: PricingPolicy) -> PricingPolicyRead:
    """The staff view of a policy with its derived flags."""
    return PricingPolicyRead(
        **policy.model_dump(),
        cod_enabled=policy.cod_enabled,
        delhivery_configured=delhivery_configured(tenant),
        delhivery_b2b_configured=delhivery_b2b_configured(tenant),
    )


