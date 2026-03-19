from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class InputEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OutputEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class MessageChannel(Protocol):
    async def receive(self) -> InputEvent: ...
    async def send(self, event: OutputEvent) -> None: ...
