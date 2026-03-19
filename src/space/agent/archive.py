from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from space.agent.base import AgentLoopSettings, agent_loop
from space.llm.base import ApiMessage, LLMProvider
from space.tool.base import Tool


@dataclass(slots=True, frozen=True)
class ArchiveStage:
    name: str
    instructions: str
    max_iterations: int


class ArchiveAgent:
    def __init__(self, llm: LLMProvider, instructions: str, max_iterations: int = 16) -> None:
        self._llm = llm
        self._instructions = instructions
        self._max_iterations = max_iterations

    async def run(
        self,
        messages: list[ApiMessage],
        tools: list[Tool],
        should_stop: Callable[[], bool] | None = None,
    ) -> str:
        stage = ArchiveStage(name="archive", instructions=self._instructions, max_iterations=self._max_iterations)
        return await self.run_stage(stage=stage, messages=messages, tools=tools, should_stop=should_stop)

    async def run_stage(
        self,
        stage: ArchiveStage,
        messages: list[ApiMessage],
        tools: list[Tool],
        should_stop: Callable[[], bool] | None = None,
    ) -> str:
        scoped_messages: list[ApiMessage] = [{"role": "system", "content": stage.instructions}, *messages]
        return await agent_loop(
            llm=self._llm,
            messages=scoped_messages,
            tools=tools,
            settings=AgentLoopSettings(
                max_iterations=stage.max_iterations,
                should_stop=should_stop,
                finish_tool_name="finish_stage",
            ),
        )
