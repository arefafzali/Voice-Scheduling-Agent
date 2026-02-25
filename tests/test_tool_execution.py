from __future__ import annotations

import pytest

from app.adapters.mcp_tool_adapter import MCPToolAdapter
from app.domain.schemas import ToolExecutionRequest
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"

    def execute(self, payload: dict, context: dict | None = None) -> dict:
        return {"echo": payload}


def test_mcp_adapter_routes_to_registry() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    adapter = MCPToolAdapter(registry)
    request = ToolExecutionRequest(tool_name="echo", payload={"value": 123})

    response = adapter.invoke(request)
    assert response.tool_name == "echo"
    assert response.result == {"echo": {"value": 123}}


def test_mcp_adapter_raises_for_unknown_tool() -> None:
    adapter = MCPToolAdapter(ToolRegistry())
    request = ToolExecutionRequest(tool_name="missing_tool", payload={})

    with pytest.raises(KeyError):
        adapter.invoke(request)
