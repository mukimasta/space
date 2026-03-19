from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

MessageRole = Literal["system", "user", "assistant", "tool"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Message:
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=_utc_now)


@dataclass(slots=True, frozen=True)
class Space:
    name: str
    path: str


@dataclass(slots=True, frozen=True)
class LoadedSpace:
    space: Space
    space_markdown: str
    contexts: dict[str, str]


@dataclass(slots=True, frozen=True)
class HistoryMeta:
    space: str
    created_at: datetime
    message_count: int
    title: str | None = None
    record_path: str | None = None


@dataclass(slots=True)
class AppState:
    space: Space | None = None
    conversation: list[Message] = field(default_factory=list)
    model: str = "openai/gpt-4o-mini"
    provider: str = "openrouter"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
