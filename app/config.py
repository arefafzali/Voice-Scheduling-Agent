from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Voice Scheduling Agent"
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    default_timezone: str = Field(default="America/Montreal", alias="DEFAULT_TIMEZONE")
    default_duration_minutes: int = Field(default=30, alias="DEFAULT_DURATION_MINUTES", ge=5, le=480)

    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    database_url: str = Field(default="sqlite:///./app.db", alias="DATABASE_URL")
    session_cookie_name: str = Field(default="vsa_session", alias="SESSION_COOKIE_NAME")
    session_cookie_max_age_seconds: int = Field(default=2592000, alias="SESSION_COOKIE_MAX_AGE_SECONDS")
    session_cookie_secure: bool = Field(default=False, alias="SESSION_COOKIE_SECURE")
    session_secret_key: str = Field(default="dev-only-change-me", alias="SESSION_SECRET_KEY")
    csrf_cookie_name: str = Field(default="vsa_csrf", alias="CSRF_COOKIE_NAME")
    csrf_header_name: str = Field(default="X-CSRF-Token", alias="CSRF_HEADER_NAME")

    google_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_ID")
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="http://localhost:8000/api/auth/google/callback", alias="GOOGLE_REDIRECT_URI")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")


settings = Settings()
