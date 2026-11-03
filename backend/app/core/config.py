from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # This tells Pydantic to load variables from a .env file
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Project Metadata ---
    PROJECT_NAME: str = "Naviera API"
    API_V1_STR: str = "/api/v1"
    DOCS_ENDPOINT: str = "/docs"

    # The database URL, which Pydantic will automatically load from the .env file
    DATABASE_URL: str

    ALEMBIC_DATABASE_URL: str

    # New setting to control SQL query logging
    # It's a boolean that defaults to False if not set in the .env file
    DB_ECHO_LOG: bool = False

    CONSOLE_LOG: bool = False

    # --- Authentication ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Supabase Client ---
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    # Add the Supabase Issuer URL
    JWT_ISSUER: str

    ENVIRONMENT: str

    # --- Logging ---
    LOGFIRE_TOKEN: str = ""

    # --- Delhivery B2C (Express) API: live prices for the tenants bound to the token ---
    # Token from one.delhivery.com → Settings → API Setup (prod; staging prices are ₹0).
    # Empty = Delhivery options show "price unavailable". See docs/RUNBOOK.md "Delhivery API token".
    DELHIVERY_B2C_TOKEN: str = ""
    DELHIVERY_B2C_BASE_URL: str = "https://track.delhivery.com"
    DELHIVERY_TENANT_ID: str = ""
    """UUID of the tenant whose Delhivery account the token belongs to (live `logismart`)."""
    DELHIVERY_LIVE_TENANT_SLUGS: str = ""
    """Comma-separated slugs that also use the live Delhivery accounts (e.g. `logismart,logismart-test`)."""
    DELHIVERY_FAKE_TENANT_SLUGS: str = ""
    """Comma-separated slugs priced by the deterministic fake instead; wins over the live binding. Set
    only by the test harness (`run_golden.sh`, `scripts/tests/conftest.py`) and the Cloudtop
    `backend/.env` whose `:8000` serves the UI golden phase. Unset on Render."""

    # --- Delhivery B2B (Cargo / LTL) API: live freight estimates, same bound tenant ---
    # Username + password of Logismart's Delhivery B2B account (`POST /ums/login` → 24 h JWT).
    # Empty = the "Delhivery B2B Cargo" option shows "price unavailable". Production host
    # only: staging has no pricing file. See llm_resources/.agents/pricing/delhivery_b2b_api.md.
    DELHIVERY_B2B_USERNAME: str = ""
    DELHIVERY_B2B_PASSWORD: str = ""
    DELHIVERY_B2B_BASE_URL: str = "https://ltl-clients-api.delhivery.com"


settings = Settings()  # type: ignore

PRODUCTION_ENVIRONMENT = "production"
"""`ENVIRONMENT` value on Render (docs/RUNBOOK.md go-live checklist)."""


def is_production() -> bool:
    """True on the live deployment (API docs hidden, no local rate-limit exemption)."""
    return settings.ENVIRONMENT.strip().lower() == PRODUCTION_ENVIRONMENT
