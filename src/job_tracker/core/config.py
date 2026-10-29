from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Job Application Tracker"
    environment: Literal["local", "test", "production"] = "local"
    debug: bool = False

    # Local development default only; production must set DATABASE_URL explicitly.
    database_url: str = "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker"
    database_echo: bool = False

    @model_validator(mode="after")
    def require_explicit_database_url_in_production(self) -> Self:
        """Refuse to start production with the local development database URL."""
        if self.environment == "production" and "database_url" not in self.model_fields_set:
            raise ValueError("DATABASE_URL must be set explicitly in production")
        return self

    @model_validator(mode="after")
    def forbid_debug_in_production(self) -> Self:
        """Refuse to start production in debug mode.

        With ``debug=True`` Starlette answers unhandled exceptions with a page showing the
        traceback and source code instead of the generic 500 response (D-17).
        """
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must not be enabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the settings, read from the environment once and cached."""
    return Settings()
