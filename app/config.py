from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with explicit demo/prod mode validation."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_mode: Literal["demo", "prod"] = Field(default="demo", alias="APP_MODE")
    app_name: str = Field(default="Voice Scheduling Agent", alias="APP_NAME")
    log_level: str = Field(default="", alias="LOG_LEVEL")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"],
        alias="CORS_ORIGINS",
    )
    admin_token: str | None = Field(default=None, alias="ADMIN_TOKEN")
    enable_logs_endpoint: bool = Field(default=True, alias="ENABLE_LOGS_ENDPOINT")
    enable_debug_endpoints: bool = Field(default=True, alias="ENABLE_DEBUG_ENDPOINTS")

    default_timezone: str = Field(default="America/Montreal", alias="DEFAULT_TIMEZONE")
    default_duration_minutes: int = Field(default=30, alias="DEFAULT_DURATION_MINUTES", ge=5, le=480)

    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    database_url: str = Field(default="sqlite:///./app.db", alias="DATABASE_URL")
    db_require_migrations: bool = Field(default=False, alias="DB_REQUIRE_MIGRATIONS")

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
    google_oauth_auth_uri: str = Field(default="https://accounts.google.com/o/oauth2/auth", alias="GOOGLE_OAUTH_AUTH_URI")
    google_oauth_token_uri: str = Field(default="https://oauth2.googleapis.com/token", alias="GOOGLE_OAUTH_TOKEN_URI")
    google_calendar_scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/calendar.events"],
        alias="GOOGLE_CALENDAR_SCOPES",
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_realtime_model: str = Field(default="gpt-4o-realtime-preview", alias="OPENAI_REALTIME_MODEL")
    openai_realtime_voice: str = Field(default="alloy", alias="OPENAI_REALTIME_VOICE")
    openai_realtime_webrtc_url: str = Field(
        default="https://api.openai.com/v1/realtime",
        alias="OPENAI_REALTIME_WEBRTC_URL",
    )
    openai_realtime_sessions_url: str = Field(
        default="https://api.openai.com/v1/realtime/sessions",
        alias="OPENAI_REALTIME_SESSIONS_URL",
    )
    openai_transcription_model: str = Field(default="gpt-4o-mini-transcribe", alias="OPENAI_TRANSCRIPTION_MODEL")
    openai_transcription_language: str = Field(default="en", alias="OPENAI_TRANSCRIPTION_LANGUAGE")
    openai_realtime_instructions: str = Field(
        default=(
            "You are a voice scheduling assistant. Start by greeting the user and collecting exactly these fields: "
            "name, date, time, and optional title. If title is missing, use 'Meeting with {name}'. "
            "Never call create_calendar_event until the user has explicitly confirmed all details. "
            "Before confirmation, summarize all details and ask for a clear yes/no confirmation. "
            "If details are ambiguous, ask a focused follow-up question."
        ),
        alias="OPENAI_REALTIME_INSTRUCTIONS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return [item.strip() for item in value if item and item.strip()]
        if not isinstance(value, str) or not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("google_calendar_scopes", mode="before")
    @classmethod
    def parse_google_calendar_scopes(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return [item.strip() for item in value if item and item.strip()]
        if not isinstance(value, str) or not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def is_demo(self) -> bool:
        return self.app_mode == "demo"

    @property
    def is_prod(self) -> bool:
        return self.app_mode == "prod"

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if not self.log_level.strip():
            self.log_level = "DEBUG" if self.is_demo else "INFO"

        if self.is_prod:
            self.enable_logs_endpoint = False
            self.enable_debug_endpoints = False
            self.db_require_migrations = True

        missing: list[str] = []
        if not self.google_client_id.strip():
            missing.append("GOOGLE_CLIENT_ID")
        if not self.google_client_secret.strip():
            missing.append("GOOGLE_CLIENT_SECRET")
        if not self.google_redirect_uri.strip():
            missing.append("GOOGLE_REDIRECT_URI")
        if not self.openai_api_key.strip():
            missing.append("OPENAI_API_KEY")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")

        if not self.cors_origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")

        if not self.google_calendar_scopes:
            raise ValueError("GOOGLE_CALENDAR_SCOPES must contain at least one OAuth scope")

        if self.is_prod:
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true in production")
            if self.session_secret_key == "dev-only-change-me":
                raise ValueError("SESSION_SECRET_KEY must be set to a strong non-default value in production")
            if any(origin == "*" for origin in self.cors_origins):
                raise ValueError("CORS_ORIGINS cannot include '*' in prod mode")
            if self.app_base_url.startswith("http://"):
                raise ValueError("APP_BASE_URL must be https:// in prod mode")
        return self


settings = Settings()
