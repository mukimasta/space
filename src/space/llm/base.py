from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

ApiMessage = dict[str, Any]
ToolDef = dict[str, Any]


@dataclass(slots=True, frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None


@dataclass(slots=True, frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True, frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] | None = None
    usage: LLMUsage | None = None


class LLMProvider(Protocol):
    async def generate(
        self,
        messages: list[ApiMessage],
        tools: list[ToolDef] | None = None,
    ) -> LLMResponse: ...

    async def stream(self, messages: list[ApiMessage]) -> AsyncIterator[str]: ...

    async def list_models(self) -> list[str]: ...
