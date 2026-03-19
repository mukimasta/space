from __future__ import annotations

import json
from typing import Any

from space.channel.base import InputEvent, MessageChannel, OutputEvent
from space.tool.base import BaseTool


class ConfirmTool(BaseTool):
    name = "confirm"
    description = "Ask user to approve, reject, or revise a proposed content block."
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short action title for user confirmation."},
            "content": {"type": "string", "description": "Draft content to review."},
        },
        "required": ["title", "content"],
        "additionalProperties": False,
    }

    def __init__(self, channel: MessageChannel) -> None:
        self._channel = channel

    async def execute(self, **kwargs: str) -> str:
        title = kwargs["title"]
        content = kwargs["content"]
        await self._channel.send(
            OutputEvent(
                kind="confirm_request",
                payload={
                    "title": title,
                    "content": content,
                },
            )
        )
        response = await self._channel.receive()
        parsed = self._parse_response(response)
        return json.dumps(parsed, ensure_ascii=False)

    @staticmethod
    def _parse_response(event: InputEvent) -> dict[str, Any]:
        if event.kind != "confirm_response":
            return {"decision": "reject", "reason": f"unexpected event kind: {event.kind}"}
        decision = str(event.payload.get("decision", "reject")).lower()
        if decision not in {"approve", "reject", "edit"}:
            decision = "reject"
        parsed: dict[str, Any] = {"decision": decision}
        if "content" in event.payload:
            parsed["content"] = event.payload["content"]
        if "reason" in event.payload:
            parsed["reason"] = event.payload["reason"]
        return parsed
