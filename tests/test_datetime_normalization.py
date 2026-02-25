from __future__ import annotations

from datetime import date, time
from app.domain.schemas import ConversationStage, SessionState
from app.services.conversation import ConversationService
from app.services.llm_agent import AgentInterpretation, SchedulingLLMAgent
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class CaptureTool(Tool):
    name = "create_calendar_event"

    def __init__(self) -> None:
        self.calls = 0
        self.last_payload = {}

    def execute(self, payload: dict, context: dict | None = None) -> dict:
        self.calls += 1
        self.last_payload = payload
        return {"event_id": "evt_123", "html_link": "https://calendar.google.com/event?eid=evt_123"}


class StubAgent(SchedulingLLMAgent):
    def __init__(self, interpretations: list[AgentInterpretation]) -> None:
        self._interpretations = interpretations

    def interpret_turn(self, state: SessionState, user_message: str) -> AgentInterpretation:
        if not self._interpretations:
            raise AssertionError("No more stub interpretations")
        return self._interpretations.pop(0)


def test_llm_ambiguous_time_moves_to_collect_time() -> None:
    registry = ToolRegistry()
    agent = StubAgent(
        [
            AgentInterpretation(
                assistant_message="Please give exact time",
                extracted_date=date(2026, 3, 4),
                ambiguous_datetime=True,
            )
        ]
    )
    service = ConversationService(registry, llm_agent=agent, default_timezone="America/Montreal", default_duration=30)

    state = SessionState(name="Afzal", stage=ConversationStage.COLLECT_DATE)
    response = service.process_turn(state, "tomorrow afternoon")

    assert response.state.stage == ConversationStage.COLLECT_TIME
    assert response.state.preferred_date == date(2026, 3, 4)


def test_confirmation_gate_and_timezone_aware_payload() -> None:
    agent = StubAgent(
        [
            AgentInterpretation(assistant_message="Need confirmation", confirmation_intent="decline"),
            AgentInterpretation(assistant_message="creating", confirmation_intent="confirm"),
        ]
    )

    capture_tool = CaptureTool()
    registry = ToolRegistry()
    registry.register(capture_tool)
    service = ConversationService(registry, llm_agent=agent, default_timezone="America/Montreal", default_duration=30)

    state = SessionState(
        name="Afzal",
        stage=ConversationStage.CONFIRM,
        preferred_date=date(2026, 3, 3),
        preferred_time=time(10, 0),
        timezone="America/Montreal",
        duration_minutes=30,
    )

    no_response = service.process_turn(state, "no")
    assert no_response.state.stage == ConversationStage.CORRECTION
    assert capture_tool.calls == 0

    confirmed_state = SessionState(
        name="Afzal",
        stage=ConversationStage.CONFIRM,
        preferred_date=date(2026, 3, 3),
        preferred_time=time(10, 0),
        timezone="America/Montreal",
        duration_minutes=30,
    )
    yes_response = service.process_turn(confirmed_state, "yes")

    assert yes_response.state.stage in {ConversationStage.COMPLETED, ConversationStage.CONFIRM}


def test_collect_name_preserves_prefilled_details() -> None:
    registry = ToolRegistry()
    agent = StubAgent(
        [
            AgentInterpretation(
                assistant_message="Please share your name",
                extracted_date=date(2026, 2, 26),
                extracted_time=time(17, 0),
                extracted_title="ML role",
            ),
            AgentInterpretation(
                assistant_message="Thanks",
                extracted_name="Aref",
            ),
        ]
    )
    service = ConversationService(registry, llm_agent=agent, default_timezone="America/Montreal", default_duration=30)

    state = SessionState(stage=ConversationStage.COLLECT_NAME)
    first = service.process_turn(state, "schedule meeting tomorrow now for ML role")
    assert first.state.stage == ConversationStage.COLLECT_NAME
    assert first.state.preferred_date == date(2026, 2, 26)
    assert first.state.preferred_time == time(17, 0)
    assert first.state.title == "ML role"

    second = service.process_turn(first.state, "Aref")
    assert second.state.stage == ConversationStage.CONFIRM
