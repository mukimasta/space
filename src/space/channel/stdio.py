from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable

from space.channel.base import InputEvent, OutputEvent


class StdioChannel:
    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input_fn = input_fn
        self._output_fn = output_fn
        self._pending_requests: deque[OutputEvent] = deque()

    async def send(self, event: OutputEvent) -> None:
        self._pending_requests.append(event)
        if event.kind == "confirm_request":
            title = str(event.payload.get("title", "Confirm"))
            content = str(event.payload.get("content", ""))
            self._output_fn("")
            self._output_fn(f"[confirm] {title}")
            if content:
                self._output_fn(content)
            self._output_fn("输入: approve / edit / reject")
        else:
            self._output_fn(f"[event:{event.kind}] {event.payload}")

    async def receive(self) -> InputEvent:
        if self._pending_requests:
            request = self._pending_requests.popleft()
            if request.kind == "confirm_request":
                return await self._receive_confirm_response()
        raw = await asyncio.to_thread(self._input_fn, "event> ")
        return InputEvent(kind="text", payload={"text": raw})

    async def _receive_confirm_response(self) -> InputEvent:
        decision = (await asyncio.to_thread(self._input_fn, "decision> ")).strip().lower()
        if decision == "approve":
            return InputEvent(kind="confirm_response", payload={"decision": "approve"})
        if decision == "reject":
            reason = (await asyncio.to_thread(self._input_fn, "reason(optional)> ")).strip()
            payload = {"decision": "reject"}
            if reason:
                payload["reason"] = reason
            return InputEvent(kind="confirm_response", payload=payload)
        if decision == "edit":
            content = await asyncio.to_thread(self._input_fn, "edited content> ")
            return InputEvent(
                kind="confirm_response",
                payload={
                    "decision": "edit",
                    "content": content,
                },
            )
        return InputEvent(
            kind="confirm_response",
            payload={"decision": "reject", "reason": f"invalid decision: {decision}"},
        )
