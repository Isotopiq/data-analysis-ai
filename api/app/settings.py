from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/appdb"
    target_database_url: str = "postgresql+asyncpg://app:app@localhost:5432/appdb"

    executor_url: str = "http://localhost:8001"

    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = ""
    openai_api_key: str = ""
    api_secret_key: str = "dev-only-secret-change-me"

    cors_origins: str = "http://localhost:3000"

    # Auth
    auth_jwt_secret: str = "dev-only-jwt-secret-change-me"
    auth_cookie_name: str = "uda_session"
    auth_token_ttl_minutes: int = 60 * 24 * 7
    admin_username: str = "admin"
    admin_password: str = "admin"


settings = Settings()
