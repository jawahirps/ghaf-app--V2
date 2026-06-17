"""
Ghaf App — application configuration.

Settings are loaded from environment variables / a .env file. See
backend/.env.example for the full list of supported variables.
"""
from functools import lru_cache
from typing import Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Ghaf App"
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "sqlite:///./ghaf_app.db"

    # Auth / JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    # Metabase embedding (Analytics & Financial Insights tab)
    METABASE_SITE_URL: str = "http://localhost:3000"
    METABASE_SECRET_KEY: str = ""
    METABASE_TOKEN_EXPIRY_SECONDS: int = 600

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Mapping of dashboard "keys" used by the React Analytics & Financial Insights
# tab to actual Metabase dashboard IDs. Update these to match the dashboards
# created in your Metabase instance (Settings > Embedding must be enabled,
# and each dashboard must be marked as "Embedding enabled").
METABASE_DASHBOARDS: Dict[str, int] = {
    "financial_overview": 1,
    "payer_breakdown": 2,
    "collections": 3,
    "ar_aging": 4,
    "denials": 5,
}
