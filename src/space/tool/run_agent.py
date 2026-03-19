from __future__ import annotations

from typing import Any, Awaitable, Callable

from space.tool.base import BaseTool

RunAgentCallable = Callable[[str, list[dict[str, Any]]], Awaitable[str]]


class RunAgentTool(BaseTool):
    name = "run_agent"
    description = "Run another registered agent as a sub-task and return its final output."
    parameters = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Registered agent name."},
            "messages": {
                "type": "array",
                "description": "Messages passed to the target agent.",
                "items": {"type": "object"},
            },
        },
        "required": ["agent", "messages"],
        "additionalProperties": False,
    }

    def __init__(self, runner: RunAgentCallable) -> None:
        self._runner = runner

    async def execute(self, **kwargs: Any) -> str:
        agent = str(kwargs["agent"])
        messages = kwargs["messages"]
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")
        normalized: list[dict[str, Any]] = []
        for item in messages:
            if not isinstance(item, dict):
                raise ValueError("each message must be an object")
            normalized.append(item)
        return await self._runner(agent, normalized)
