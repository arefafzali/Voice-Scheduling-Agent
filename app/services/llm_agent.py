from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from app.domain.schemas import ConversationStage, SessionState


@dataclass
class AgentInterpretation:
    assistant_message: str
    extracted_name: str | None = None
    extracted_date: date | None = None
    extracted_time: time | None = None
    extracted_title: str | None = None
    skip_title: bool = False
    extracted_timezone: str | None = None
    extracted_duration_minutes: int | None = None
    confirmation_intent: Literal["confirm", "decline", "none"] = "none"
    ambiguous_datetime: bool = False


class SchedulingLLMAgent:
    def interpret_turn(self, state: SessionState, user_message: str) -> AgentInterpretation:
        raise NotImplementedError


class OpenAISchedulingAgent(SchedulingLLMAgent):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for LLM agent orchestration")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required") from exc

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def interpret_turn(self, state: SessionState, user_message: str) -> AgentInterpretation:
        reference_now = datetime.now(ZoneInfo(state.timezone or "America/Montreal"))
        system_prompt = (
            "You are the reasoning and response engine for a voice scheduling assistant. Return only JSON. "
            "Always generate a natural, context-aware assistant_message for this specific turn. "
            "Do not return generic placeholders. Do not repeat a fixed script. "
            "Extract structured fields from the user's message and conversation context. "
            "Rules: default timezone America/Montreal, default duration 30 unless user specifies, "
            "title is optional and must never block progress; if omitted allow skip_title=true. "
            "If name/date/time are present, move to confirmation summary. "
            "Always require explicit user confirmation before event creation. "
            "Identify confirm/decline intents. "
            "If user gives ambiguous time/date like 'tomorrow afternoon', set ambiguous_datetime=true. "
            "Never claim an event was created. "
            "If information is missing for scheduling, ask exactly for the missing field in assistant_message. "
            "Use reference_datetime and timezone for all relative time resolution (today, tomorrow, now). "
            "Never contradict already-collected state values unless user is explicitly correcting them. "
            "Current real date/time comes from reference_datetime; do not invent a different date."
        )

        user_payload = {
            "conversation_stage": state.stage.value,
            "current_state": {
                "name": state.name,
                "preferred_date": state.preferred_date.isoformat() if state.preferred_date else None,
                "preferred_time": state.preferred_time.isoformat() if state.preferred_time else None,
                "title": state.title,
                "timezone": state.timezone,
                "duration_minutes": state.duration_minutes,
            },
            "reference_datetime": reference_now.isoformat(),
            "user_message": user_message,
            "output_schema": {
                "assistant_message": "string",
                "extracted_name": "string|null",
                "extracted_date": "YYYY-MM-DD|null",
                "extracted_time": "HH:MM[:SS]|null",
                "extracted_title": "string|null",
                "skip_title": "boolean",
                "extracted_timezone": "IANA timezone string|null",
                "extracted_duration_minutes": "integer|null",
                "confirmation_intent": "confirm|decline|none",
                "ambiguous_datetime": "boolean",
            },
            "quality_rules": [
                "assistant_message must be non-empty",
                "assistant_message should reference user-provided content when possible",
                "assistant_message must guide next step when state is incomplete",
            ],
        }

        completion = self._client.chat.completions.create(
            model=self._model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
        )

        content = completion.choices[0].message.content or "{}"
        parsed = json.loads(content)

        extracted_date = self._parse_date(parsed.get("extracted_date"))
        extracted_time = self._parse_time(parsed.get("extracted_time"))

        return AgentInterpretation(
            assistant_message=str(parsed.get("assistant_message") or "Got it."),
            extracted_name=self._clean_optional_str(parsed.get("extracted_name")),
            extracted_date=extracted_date,
            extracted_time=extracted_time,
            extracted_title=self._clean_optional_str(parsed.get("extracted_title")),
            skip_title=bool(parsed.get("skip_title", False)),
            extracted_timezone=self._clean_optional_str(parsed.get("extracted_timezone")),
            extracted_duration_minutes=self._parse_int(parsed.get("extracted_duration_minutes")),
            confirmation_intent=self._parse_intent(parsed.get("confirmation_intent")),
            ambiguous_datetime=bool(parsed.get("ambiguous_datetime", False)),
        )

    def _parse_date(self, value: object) -> date | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None

    def _parse_time(self, value: object) -> time | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = value.strip()
        if len(candidate) == 5:
            candidate = f"{candidate}:00"
        try:
            parsed = time.fromisoformat(candidate)
            return parsed.replace(second=0, microsecond=0, tzinfo=None)
        except ValueError:
            return None

    def _clean_optional_str(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _parse_int(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _parse_intent(self, value: object) -> Literal["confirm", "decline", "none"]:
        if value in {"confirm", "decline", "none"}:
            return value
        return "none"
