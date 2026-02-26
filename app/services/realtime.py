from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException


class OpenAIRealtimeService:
    def __init__(
        self,
        api_key: str,
        model: str,
        voice: str,
        instructions: str,
        webrtc_url: str,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI Realtime")
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._instructions = instructions
        self._webrtc_url = webrtc_url

    @property
    def webrtc_url(self) -> str:
        return self._webrtc_url

    def _calendar_tool_schema(self) -> dict:
        return {
            "type": "function",
            "name": "create_calendar_event",
            "description": "Create a Google Calendar event after user explicitly confirms. If summary, end time, or timezone are missing, server defaults are applied.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title (optional)"},
                    "start_iso": {
                        "type": "string",
                        "description": "Start datetime in ISO 8601 with timezone offset",
                    },
                    "end_iso": {
                        "type": "string",
                        "description": "End datetime in ISO 8601 with timezone offset (optional)",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. America/Montreal (optional)",
                    },
                    "description": {"type": "string", "description": "Optional event description"},
                    "duration_minutes": {"type": "integer", "description": "Optional duration override"},
                    "name": {"type": "string", "description": "User name for default title fallback"},
                },
                "required": ["start_iso"],
                "additionalProperties": False,
            },
        }

    def create_ephemeral_session(self) -> dict:
        required_behavior = (
            "Default language is English unless the user asks for another language. "
            "Required behavior: initiate the conversation proactively. "
            "Collect the user's name, preferred date, preferred time, and optional meeting title. "
            "Use the exact name the user provides and never invent or replace it. "
            "If title is missing, use 'Meeting with {name}'. "
            "Use predefined defaults for other fields (timezone and duration) unless the user explicitly asks to change them. "
            "Do not ask for meeting duration unless the user explicitly asks to change it. "
            "Before calling create_calendar_event, summarize final details and ask for explicit confirmation. "
            "Only call create_calendar_event after a clear yes/confirm response from the user."
        )
        body = {
            "model": self._model,
            "voice": self._voice,
            "instructions": f"{self._instructions}\n\n{required_behavior}",
            "modalities": ["audio", "text"],
            "input_audio_transcription": {"model": "gpt-4o-mini-transcribe", "language": "en"},
            "turn_detection": {
                "type": "server_vad",
                "create_response": False,
                "interrupt_response": True,
                "silence_duration_ms": 1000,
                "prefix_padding_ms": 400,
            },
            "tools": [self._calendar_tool_schema()],
            "tool_choice": "auto",
        }
        request = Request(
            url="https://api.openai.com/v1/realtime/sessions",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed to create OpenAI Realtime session.",
                    "action": "Verify OPENAI_API_KEY and realtime model configuration.",
                },
            ) from exc
        except (URLError, TimeoutError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "OpenAI Realtime service is currently unavailable.",
                    "action": "Retry in a few seconds.",
                },
            ) from exc
