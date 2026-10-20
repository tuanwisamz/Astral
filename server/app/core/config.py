from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", extra="ignore")

    app_env: str = "development"

    database_url: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""

    clerk_jwks_url: str = ""
    clerk_secret_key: str = ""
    clerk_authorized_parties: str = "http://localhost:5173"
    clerk_webhook_secret: str = ""

    gemini_api_key: str = ""
    gemini_model_vision: str = "gemini-3.6-flash"
    gemini_model_lite: str = "gemini-3.5-flash-lite"
    tomtom_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    nominatim_user_agent: str = "smart-analysis-road/1.0"
    cron_secret: str = ""
    frontend_origin: str = "http://localhost:5173"

    dev_auth_role: str = ""
    dev_auth_state: str = ""  # scope for the dev role, e.g. "A" to act as a Perak officer

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def dev_auth_allowed(self) -> bool:
        """The no-token role bypass: local development and the test suite only, never production."""
        return self.app_env in ("development", "test")

    @property
    def authorized_parties(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]

    @property
    def cors_origins(self) -> list[str]:
        origins = {self.frontend_origin, *self.authorized_parties}
        if self.is_dev:
            origins |= {"http://localhost:5173", "http://127.0.0.1:5173"}
        return sorted(o for o in origins if o)


@lru_cache
def get_settings() -> Settings:
    return Settings()
