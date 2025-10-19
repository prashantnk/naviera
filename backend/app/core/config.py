from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # This tells Pydantic to load variables from a .env file
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # The database URL, which Pydantic will automatically load from the .env file
    DATABASE_URL: str

    # New setting to control SQL query logging
    # It's a boolean that defaults to False if not set in the .env file
    DB_ECHO_LOG: bool = False

settings = Settings() # type: ignore