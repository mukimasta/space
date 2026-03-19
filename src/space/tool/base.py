from __future__ import annotations

from typing import Any, Protocol

from space.llm.base import ToolDef


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    async def execute(self, **kwargs: Any) -> str: ...
    def to_api_dict(self) -> ToolDef: ...


class BaseTool:
    name = ""
    description = ""
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def to_api_dict(self) -> ToolDef:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
