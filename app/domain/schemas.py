from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings


class ConversationStage(str, Enum):
    COLLECT_NAME = "collect_name"
    COLLECT_DATE = "collect_date"
    COLLECT_TIME = "collect_time"
    COLLECT_TITLE = "collect_title"
    CONFIRM = "confirm"
    CORRECTION = "correction"
    COMPLETED = "completed"


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    stage: ConversationStage = ConversationStage.COLLECT_NAME

    name: Optional[str] = None
    preferred_date: Optional[date] = None
    preferred_time: Optional[time] = None
    title: Optional[str] = None
    timezone: str = Field(default_factory=lambda: settings.default_timezone)
    duration_minutes: int = Field(default_factory=lambda: settings.default_duration_minutes, ge=5, le=480)

    pending_clarification: Optional[str] = None
    created_event_id: Optional[str] = None
    created_event_link: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


class StartSessionResponse(BaseModel):
    session_id: str
    assistant_message: str
    state: SessionState


class UserTurnRequest(BaseModel):
    user_message: str = Field(min_length=1, max_length=2000)


class AgentTurnResponse(BaseModel):
    assistant_message: str
    state: SessionState


class CalendarEventRequest(BaseModel):
    summary: str
    start_iso: datetime
    end_iso: datetime
    timezone: str
    description: str = ""

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarEventRequest":
        if self.start_iso.tzinfo is None or self.end_iso.tzinfo is None:
            raise ValueError("start_iso and end_iso must be timezone-aware")
        timezone_obj = ZoneInfo(self.timezone)
        self.start_iso = self.start_iso.astimezone(timezone_obj)
        self.end_iso = self.end_iso.astimezone(timezone_obj)
        if self.end_iso <= self.start_iso:
            raise ValueError("end_iso must be after start_iso")
        return self


class CalendarEventResult(BaseModel):
    event_id: str
    html_link: str


class ToolExecutionRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=100)
    payload: dict


class ToolExecutionResponse(BaseModel):
    tool_name: str
    result: dict


class RealtimeSessionConfigResponse(BaseModel):
    transport: str
    sample_rate_hz: int
    input_audio_format: str
    output_audio_format: str
    default_timezone: str
    default_duration_minutes: int
    confirmation_required: bool


class RealtimeClientSecret(BaseModel):
    value: str
    expires_at: int | None = None


class RealtimeSessionResponse(BaseModel):
    id: str
    model: str
    voice: str | None = None
    webrtc_url: str
    client_secret: RealtimeClientSecret


class OAuthStartResponse(BaseModel):
    authorization_url: str


class OAuthCallbackResponse(BaseModel):
    session_id: str
    status: str


class OAuthConnectionStatusResponse(BaseModel):
    session_id: str | None
    connected: bool
