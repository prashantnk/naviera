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

    # New setting to control SQL query logging
    # It's a boolean that defaults to False if not set in the .env file
    DB_ECHO_LOG: bool = False

    # --- Authentication ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Supabase Client ---
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    # Add the Supabase Issuer URL
    JWT_ISSUER: str


settings = Settings()  # type: ignore
