from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.schemas import AgentTurnResponse, ConversationStage, SessionState
from app.services.llm_agent import SchedulingLLMAgent
from app.tools.registry import ToolRegistry
from app.tools.context import (
    get_current_db_session,
    get_current_session_id,
    reset_current_session_id,
    set_current_session_id,
)

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        tools: ToolRegistry,
        llm_agent: SchedulingLLMAgent,
        default_timezone: str,
        default_duration: int,
    ) -> None:
        self._tools = tools
        self._llm_agent = llm_agent
        self._default_timezone = default_timezone
        self._default_duration = default_duration

    def opening_prompt(self) -> str:
        return (
            "Hi! I can schedule a meeting for you. "
            "What is your name?"
        )

    def process_turn(self, state: SessionState, user_message: str) -> AgentTurnResponse:
        message = user_message.strip()
        ctx_token = set_current_session_id(state.session_id)
        decision = self._llm_agent.interpret_turn(state, message)

        try:
            if state.stage == ConversationStage.COLLECT_NAME:
                return self._handle_name(state, decision)
            if state.stage == ConversationStage.COLLECT_DATE:
                return self._handle_date(state, decision)
            if state.stage == ConversationStage.COLLECT_TIME:
                return self._handle_time(state, decision)
            if state.stage == ConversationStage.COLLECT_TITLE:
                return self._handle_title(state, decision)
            if state.stage == ConversationStage.CONFIRM:
                return self._handle_confirmation(state, decision)
            if state.stage == ConversationStage.CORRECTION:
                return self._handle_correction(state, decision)

            return AgentTurnResponse(
                assistant_message="This session is complete. Start a new one if you want another meeting.",
                state=state,
            )
        finally:
            reset_current_session_id(ctx_token)

    def _apply_common_overrides(self, state: SessionState, decision) -> None:
        if decision.extracted_timezone:
            state.timezone = decision.extracted_timezone
        if decision.extracted_duration_minutes:
            state.duration_minutes = decision.extracted_duration_minutes

    def _apply_extracted_fields(self, state: SessionState, decision) -> None:
        self._apply_common_overrides(state, decision)
        if decision.extracted_name:
            state.name = decision.extracted_name
        if decision.extracted_date:
            state.preferred_date = decision.extracted_date
        if decision.extracted_time:
            state.preferred_time = decision.extracted_time
        if decision.extracted_title:
            state.title = decision.extracted_title
        elif decision.skip_title:
            state.title = None

    def _msg(self, decision, fallback: str) -> str:
        message = (decision.assistant_message or "").strip()
        return message or fallback

    def _advance_after_collection(self, state: SessionState, decision) -> AgentTurnResponse:
        if not state.name:
            state.stage = ConversationStage.COLLECT_NAME
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "Could you share your name?"),
                state=state,
            )

        if state.preferred_date is None:
            state.stage = ConversationStage.COLLECT_DATE
            return AgentTurnResponse(
                assistant_message=self._msg(decision, f"Thanks {state.name}. What date should I use?"),
                state=state,
            )

        if state.preferred_time is None:
            state.stage = ConversationStage.COLLECT_TIME
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "What exact time should I set?"),
                state=state,
            )

        if not state.title:
            state.stage = ConversationStage.COLLECT_TITLE
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "Do you want to add an optional title? You can say skip."),
                state=state,
            )

        state.stage = ConversationStage.CONFIRM
        return AgentTurnResponse(
            assistant_message=self._msg(decision, self._build_confirmation_prompt(state)),
            state=state,
        )

    def _handle_name(self, state: SessionState, decision) -> AgentTurnResponse:
        self._apply_extracted_fields(state, decision)
        return self._advance_after_collection(state, decision)

    def _handle_date(self, state: SessionState, decision) -> AgentTurnResponse:
        self._apply_extracted_fields(state, decision)
        if state.preferred_date is None:
            state.stage = ConversationStage.COLLECT_DATE
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "Please provide a specific date."),
                state=state,
            )

        if decision.ambiguous_datetime and state.preferred_time is None:
            state.stage = ConversationStage.COLLECT_TIME
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "What exact time should I set?"),
                state=state,
            )
        return self._advance_after_collection(state, decision)

    def _handle_time(self, state: SessionState, decision) -> AgentTurnResponse:
        self._apply_extracted_fields(state, decision)

        if decision.ambiguous_datetime and state.preferred_time is None:
            state.stage = ConversationStage.COLLECT_TIME
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "Could you provide an exact time?"),
                state=state,
            )

        if state.preferred_time is None:
            state.stage = ConversationStage.COLLECT_TIME
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "I need a specific time to continue."),
                state=state,
            )
        return self._advance_after_collection(state, decision)

    def _handle_title(self, state: SessionState, decision) -> AgentTurnResponse:
        self._apply_extracted_fields(state, decision)

        if not state.title:
            state.title = f"Meeting with {state.name}"

        state.stage = ConversationStage.CONFIRM
        return AgentTurnResponse(
            assistant_message=self._msg(decision, self._build_confirmation_prompt(state)),
            state=state,
        )

    def _handle_confirmation(self, state: SessionState, decision) -> AgentTurnResponse:
        self._apply_common_overrides(state, decision)
        if decision.confirmation_intent == "confirm":
            try:
                result = self._create_event(state)
            except Exception:
                logger.exception("calendar_event_create_failed", extra={"session_id": state.session_id})
                return AgentTurnResponse(
                    assistant_message=(
                        "I couldn’t create the calendar event yet. "
                        "Please verify your Google Calendar connection and event details, then confirm again."
                    ),
                    state=state,
                )
            state.created_event_id = result["event_id"]
            state.created_event_link = result["html_link"]
            state.stage = ConversationStage.COMPLETED
            logger.info("calendar_event_created", extra={"event_id": state.created_event_id})
            return AgentTurnResponse(
                assistant_message=(
                    "Perfect — your calendar event is created. "
                    f"You can view it here: {state.created_event_link}"
                ),
                state=state,
            )

        if decision.confirmation_intent == "decline":
            state.stage = ConversationStage.CORRECTION
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "Tell me what you want to change."),
                state=state,
            )

        return AgentTurnResponse(
            assistant_message=self._msg(decision, "Please confirm or decline so I can continue."),
            state=state,
        )

    def _handle_correction(self, state: SessionState, decision) -> AgentTurnResponse:
        self._apply_extracted_fields(state, decision)
        if decision.ambiguous_datetime and state.preferred_time is None:
            state.stage = ConversationStage.COLLECT_TIME
            return AgentTurnResponse(
                assistant_message=self._msg(decision, "Could you clarify the exact time?"),
                state=state,
            )
        return self._advance_after_collection(state, decision)

    def _build_confirmation_prompt(self, state: SessionState) -> str:
        dt_label = self._meeting_start(state).strftime("%A, %B %d at %I:%M %p")
        return (
            "Please confirm the meeting details: "
            f"Title: {state.title}. "
            f"When: {dt_label}. "
            f"Timezone: {state.timezone}. "
            f"Duration: {state.duration_minutes} minutes. "
            "Should I create this event now?"
        )

    def _meeting_start(self, state: SessionState) -> datetime:
        if not state.preferred_date or not state.preferred_time:
            raise ValueError("Cannot build meeting start without date and time")

        normalized_time = state.preferred_time.replace(second=0, microsecond=0, tzinfo=None)

        return datetime.combine(
            state.preferred_date,
            normalized_time,
            tzinfo=ZoneInfo(state.timezone or self._default_timezone),
        )

    def _create_event(self, state: SessionState) -> dict[str, str]:
        meeting_start = self._meeting_start(state)
        meeting_end = meeting_start + timedelta(minutes=state.duration_minutes or self._default_duration)

        payload = {
            "summary": state.title or f"Meeting with {state.name}",
            "start_iso": meeting_start,
            "end_iso": meeting_end,
            "timezone": state.timezone or self._default_timezone,
            "description": f"Scheduled by Voice Scheduling Agent for {state.name}",
        }
        return self._tools.execute(
            "create_calendar_event",
            payload,
            context={
                "session_id": get_current_session_id() or state.session_id,
                "db": get_current_db_session(),
            },
        )
