"""
Typed validation for `Tenant.settings` updates (Platform Settings, Phase O.7 S1).

Every known section is validated with patch semantics (all fields optional) so
partial `PATCH /tenants/settings` payloads keep working. Unknown / legacy keys
pass through untouched (`extra="allow"`). Blank strings in formatted fields
(colours, emails, URLs, phones, GSTIN, UPI VPA) mean "not set" and become None.

Spring Boot Equivalent: a `@Validated` DTO tree with Bean Validation
(`@Pattern`, `@Email`, `@DecimalMin/@DecimalMax`, `@Size`).
"""

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.core.icon_registry import ALLOWED_ICON_KEYS, normalize_icon_key
from app.models.pickups import ServiceOption

HEADLINE_MAX_LENGTH = 120
PARAGRAPH_MAX_LENGTH = 1000
SHORT_TEXT_MAX_LENGTH = 255
ADDRESS_MAX_LENGTH = 500
URL_MAX_LENGTH = 2048

MARKUP_PERCENT_MAX = 200.0
MARKUP_FLAT_MAX = 100_000.0
"""Largest flat ₹ markup per shipment an admin may set."""
COD_FEE_PERCENT_MAX = 10.0
COD_FEE_MIN_MAX = 10_000.0
"""Mirror of the limits in `schemas/v1/pricing.py::PricingPolicy`."""
AUTO_DETECT_DELAY_MAX_SECONDS = 600

HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}){1,2}$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
INVOICE_PREFIX_RE = re.compile(r"^[A-Z0-9]{1,4}$")
UPI_VPA_RE = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9.-]{1,63}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{5,18}[0-9]$")
HTTP_URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)
HTTPS_URL_RE = re.compile(r"^https://[^\s/$.?#][^\s]*$", re.IGNORECASE)
LOGO_URL_RE = re.compile(
    r"^(?:https://[^\s/$.?#][^\s]*|/[A-Za-z0-9._/-]+)$", re.IGNORECASE
)


# --------------------------------------------------------------------------- helpers


def _blank_to_none(value: Any) -> Any:
    """Treats empty / whitespace-only strings as "not set"."""
    if isinstance(value, str) and not value.strip():
        return None
    return value.strip() if isinstance(value, str) else value


def _check_pattern(value: Any, pattern: re.Pattern, message: str) -> Optional[str]:
    """Blank -> None; otherwise the trimmed value must match `pattern`."""
    cleaned = _blank_to_none(value)
    if cleaned is None:
        return None
    if not isinstance(cleaned, str) or not pattern.match(cleaned):
        raise ValueError(message)
    return cleaned


class _Section(BaseModel):
    """Base for every settings section: unknown legacy keys are preserved."""

    model_config = ConfigDict(extra="allow")


# --------------------------------------------------------------------------- sections


class BrandSettings(_Section):
    """Brand colours and logo. `show_logo` defaults to True (admin toggle)."""

    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    logo_url: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)
    show_logo: Optional[bool] = None

    @field_validator("primary_color", "secondary_color", mode="before")
    @classmethod
    def _validate_hex(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, HEX_COLOR_RE, "must be a hex colour like #0F172A")

    @field_validator("logo_url", mode="before")
    @classmethod
    def _validate_logo_url(cls, value: Any) -> Optional[str]:
        return _check_pattern(
            value, LOGO_URL_RE, "must be an https:// URL or a /public asset path"
        )


class AnnouncementBarSettings(_Section):
    is_active: Optional[bool] = None
    text: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)


class SocialLinks(_Section):
    """Social profile URLs (http/https)."""

    facebook: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)
    instagram: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)
    linkedin: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)
    youtube: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)
    twitter: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)
    x: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)

    @field_validator("facebook", "instagram", "linkedin", "youtube", "twitter", "x", mode="before")
    @classmethod
    def _validate_url(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, HTTP_URL_RE, "must be an http(s):// URL")


class ContactSettings(_Section):
    """Public contact details and support channels."""

    toll_free: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = Field(default=None, max_length=ADDRESS_MAX_LENGTH)
    phones: Optional[List[str]] = None
    emails: Optional[List[EmailStr]] = None
    gstin: Optional[str] = None
    socials: Optional[SocialLinks] = None

    @field_validator("toll_free", "whatsapp", mode="before")
    @classmethod
    def _validate_phone(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, PHONE_RE, "must be a valid phone number")

    @field_validator("phones", mode="before")
    @classmethod
    def _validate_phones(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        cleaned = [_blank_to_none(v) for v in value]
        return [
            _check_pattern(v, PHONE_RE, f"'{v}' is not a valid phone number")
            for v in cleaned
            if v is not None
        ]

    @field_validator("emails", mode="before")
    @classmethod
    def _drop_blank_emails(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [v.strip() for v in value if isinstance(v, str) and v.strip()]

    @field_validator("gstin", mode="before")
    @classmethod
    def _validate_gstin(cls, value: Any) -> Optional[str]:
        upper = value.upper() if isinstance(value, str) else value
        return _check_pattern(upper, GSTIN_RE, "must be a valid 15-character GSTIN")


class OfferItem(_Section):
    title: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    description: Optional[str] = Field(default=None, max_length=PARAGRAPH_MAX_LENGTH)


class ServiceItem(_Section):
    """A Services page card. `icon` must be a key from `app/core/icon_registry.py`."""

    title: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    description: Optional[str] = Field(default=None, max_length=PARAGRAPH_MAX_LENGTH)
    icon: Optional[str] = None

    @field_validator("icon", mode="before")
    @classmethod
    def _validate_icon(cls, value: Any) -> Optional[str]:
        cleaned = _blank_to_none(value)
        if cleaned is None:
            return None
        key = normalize_icon_key(cleaned) if isinstance(cleaned, str) else None
        if key is None:
            allowed = ", ".join(sorted(ALLOWED_ICON_KEYS))
            raise ValueError(f"unknown icon '{cleaned}'. Choose one of: {allowed}")
        return key


class AboutPageSettings(_Section):
    headline: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    paragraphs: Optional[List[str]] = None
    offersHeadline: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    offers: Optional[List[OfferItem]] = None

    @field_validator("paragraphs")
    @classmethod
    def _paragraph_lengths(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        for paragraph in value or []:
            if len(paragraph) > PARAGRAPH_MAX_LENGTH:
                raise ValueError(f"each paragraph must be at most {PARAGRAPH_MAX_LENGTH} characters")
        return value


class ServicesPageSettings(_Section):
    headline: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    description: Optional[str] = Field(default=None, max_length=PARAGRAPH_MAX_LENGTH)
    valueAddHeadline: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    valueAddDescription: Optional[str] = Field(default=None, max_length=PARAGRAPH_MAX_LENGTH)
    valueAdds: Optional[List[str]] = None
    services: Optional[List[ServiceItem]] = None

    @field_validator("valueAdds")
    @classmethod
    def _value_add_lengths(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        for item in value or []:
            if len(item) > SHORT_TEXT_MAX_LENGTH:
                raise ValueError(f"each value-add must be at most {SHORT_TEXT_MAX_LENGTH} characters")
        return value


class EscalationContact(_Section):
    level: Optional[str] = Field(default=None, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("phone", mode="before")
    @classmethod
    def _validate_phone(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, PHONE_RE, "must be a valid phone number")


class LandingBlockContent(_Section):
    """Known text fields of landing-page blocks (HERO, FEATURES, ...)."""

    badge: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    title: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    headline: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)
    subtitle: Optional[str] = Field(default=None, max_length=PARAGRAPH_MAX_LENGTH)
    subheadline: Optional[str] = Field(default=None, max_length=PARAGRAPH_MAX_LENGTH)
    ctaText: Optional[str] = Field(default=None, max_length=HEADLINE_MAX_LENGTH)


class LandingBlock(_Section):
    type: Optional[str] = Field(default=None, max_length=50)
    content: Optional[LandingBlockContent] = None


class LandingPageSettings(_Section):
    blocks: Optional[List[LandingBlock]] = None


class WalletConfigSettings(_Section):
    """Unified Wallet / UPI configuration."""

    merchant_vpa: Optional[str] = None
    merchant_name: Optional[str] = Field(default=None, max_length=100)
    min_wallet_balance_b2c: Optional[float] = Field(default=None, ge=0)
    min_wallet_balance_b2b: Optional[float] = Field(default=None, ge=0)
    strict_finlock: Optional[bool] = None
    auto_detect_upi: Optional[bool] = None
    auto_detect_delay_seconds: Optional[int] = Field(
        default=None, ge=0, le=AUTO_DETECT_DELAY_MAX_SECONDS
    )
    gstin: Optional[str] = None

    @field_validator("merchant_vpa", mode="before")
    @classmethod
    def _validate_vpa(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, UPI_VPA_RE, "must be a UPI ID like name@bank")

    @field_validator("gstin", mode="before")
    @classmethod
    def _validate_gstin(cls, value: Any) -> Optional[str]:
        upper = value.upper() if isinstance(value, str) else value
        return _check_pattern(upper, GSTIN_RE, "must be a valid 15-character GSTIN")


class MarkupMode(str, Enum):
    """How Logismart's markup on a carrier cost is expressed."""

    PERCENT = "PERCENT"
    """`value` % of the carrier cost (per cost line)."""
    FLAT = "FLAT"
    """`value` rupees added once per shipment leg."""


class OptionMarkup(BaseModel):
    """One service option's markup rule (`pricing_policy.option_markups[<option>]`)."""

    model_config = ConfigDict(extra="forbid")

    mode: MarkupMode = MarkupMode.PERCENT
    value: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _within_limits(self) -> "OptionMarkup":
        """PERCENT ≤ MARKUP_PERCENT_MAX; FLAT ≤ MARKUP_FLAT_MAX rupees."""
        limit = MARKUP_PERCENT_MAX if self.mode == MarkupMode.PERCENT else MARKUP_FLAT_MAX
        if self.value > limit:
            raise ValueError(f"{self.mode.value} markup must be at most {limit:g}.")
        return self


class PricingPolicySettings(_Section):
    """
    Patch form of the staff-only selling policy (pricing redesign; replaces the old
    `pricing_config` rate card). The typed editor is `PUT /api/v1/pricing/policy`;
    this keeps a generic settings PATCH from storing an invalid policy.
    """

    delhivery_markup_percent: Optional[float] = Field(default=None, ge=0, le=MARKUP_PERCENT_MAX)
    prime_default_markup_percent: Optional[float] = Field(default=None, ge=0, le=MARKUP_PERCENT_MAX)
    cod_fee_percent: Optional[float] = Field(default=None, ge=0, le=COD_FEE_PERCENT_MAX)
    cod_fee_min: Optional[float] = Field(default=None, ge=0, le=COD_FEE_MIN_MAX)
    enabled_options: Optional[List[ServiceOption]] = None
    option_markups: Optional[Dict[ServiceOption, OptionMarkup]] = None


class OperationsSettings(_Section):
    """Operations and logistics configuration."""
    pickup_cutoff_time: Optional[str] = None


class SupportSettings(_Section):
    """Support & Help Center configuration."""

    help_center_url: Optional[str] = Field(default=None, max_length=URL_MAX_LENGTH)

    @field_validator("help_center_url", mode="before")
    @classmethod
    def _validate_help_center_url(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, HTTPS_URL_RE, "must be an https:// URL")


class CompanySettings(BaseModel):
    """
    Supplier legal / GST identity (`settings.company`). Unknown keys are forbidden
    and `invoice_prefix` is validated as 1-4 uppercase alphanumeric characters
    (and locked once configured in `TenantService.update_tenant_settings`, A4-33).
    """

    model_config = ConfigDict(extra="forbid")

    legal_name: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    display_name: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: Optional[str] = Field(default=None, max_length=10)
    state_name: Optional[str] = Field(default=None, max_length=100)
    registered_address: Optional[str] = Field(default=None, max_length=ADDRESS_MAX_LENGTH)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    invoice_prefix: Optional[str] = None

    @field_validator("gstin", mode="before")
    @classmethod
    def _validate_gstin(cls, value: Any) -> Optional[str]:
        upper = value.upper() if isinstance(value, str) else value
        return _check_pattern(upper, GSTIN_RE, "must be a valid 15-character GSTIN")

    @field_validator("pan", mode="before")
    @classmethod
    def _validate_pan(cls, value: Any) -> Optional[str]:
        upper = value.upper() if isinstance(value, str) else value
        return _check_pattern(upper, PAN_RE, "must be a valid 10-character PAN")

    @field_validator("contact_email", mode="before")
    @classmethod
    def _blank_email(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("contact_phone", mode="before")
    @classmethod
    def _validate_phone(cls, value: Any) -> Optional[str]:
        return _check_pattern(value, PHONE_RE, "must be a valid phone number")

    @field_validator("invoice_prefix", mode="before")
    @classmethod
    def _validate_prefix(cls, value: Any) -> Optional[str]:
        upper = value.upper() if isinstance(value, str) else value
        return _check_pattern(
            upper,
            INVOICE_PREFIX_RE,
            "must be 1 to 4 uppercase alphanumeric characters (e.g. LGSM)",
        )


class TenantSettingsUpdate(BaseModel):
    """
    Root of a settings patch (A4-33). Unknown root keys (including retired
    `pricing_config` or internal `b2b_access_requests`) are rejected with 422.
    """

    model_config = ConfigDict(extra="forbid")

    brand: Optional[BrandSettings] = None
    announcement_bar: Optional[AnnouncementBarSettings] = None
    contact: Optional[ContactSettings] = None
    support: Optional[SupportSettings] = None
    about_page: Optional[AboutPageSettings] = None
    services_page: Optional[ServicesPageSettings] = None
    escalation_matrix: Optional[List[EscalationContact]] = None
    landing_page: Optional[LandingPageSettings] = None
    wallet_config: Optional[WalletConfigSettings] = None
    pricing_policy: Optional[PricingPolicySettings] = None
    operations: Optional[OperationsSettings] = None
    company: Optional[CompanySettings] = None
    oAuthSignInEnabled: Optional[bool] = None
    gstin: Optional[str] = None

    @field_validator("gstin", mode="before")
    @classmethod
    def _validate_gstin(cls, value: Any) -> Optional[str]:
        upper = value.upper() if isinstance(value, str) else value
        return _check_pattern(upper, GSTIN_RE, "must be a valid 15-character GSTIN")
