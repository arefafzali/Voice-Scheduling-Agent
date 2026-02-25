from __future__ import annotations

from app.domain.schemas import ToolExecutionRequest, ToolExecutionResponse
from app.tools.registry import ToolRegistry


class MCPToolAdapter:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def invoke(self, request: ToolExecutionRequest, context: dict | None = None) -> ToolExecutionResponse:
        result = self._registry.execute(request.tool_name, request.payload, context=context)
        return ToolExecutionResponse(tool_name=request.tool_name, result=result)
