from __future__ import annotations

from typing import AsyncIterator

from space.llm.base import ApiMessage, LLMProvider


class ChatAgent:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, messages: list[ApiMessage]) -> AsyncIterator[str]:
        async for chunk in self._llm.stream(messages):
            yield chunk
