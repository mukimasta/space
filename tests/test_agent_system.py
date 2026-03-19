from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from space.agent.archive import ArchiveAgent, ArchiveStage
from space.agent.base import (
    AgentInterruptedError,
    AgentLoopLimitError,
    AgentLoopSettings,
    agent_loop,
)
from space.agent.chat import ChatAgent
from space.llm.base import LLMResponse, ToolCall
from space.tool.base import BaseTool


class FakeLLM:
    def __init__(
        self,
        responses: list[LLMResponse] | None = None,
        stream_chunks: list[str] | None = None,
    ) -> None:
        self._responses = responses or []
        self._stream_chunks = stream_chunks or []
        self.generate_calls = 0

    async def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        if self.generate_calls >= len(self._responses):
            return LLMResponse(content=None, tool_calls=None)
        response = self._responses[self.generate_calls]
        self.generate_calls += 1
        return response

    async def stream(self, _: list[dict[str, Any]]) -> AsyncIterator[str]:
        for chunk in self._stream_chunks:
            yield chunk


class EchoTool(BaseTool):
    name = "echo"
    description = "echo back text"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"echo:{kwargs['text']}"


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_calls() -> None:
    llm = FakeLLM(
        responses=[
            LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
            LLMResponse(content="done", tool_calls=None),
        ]
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": "start"}]
    result = await agent_loop(llm, messages, tools=[EchoTool()])

    assert result == "done"
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert tool_messages[0]["content"] == "echo:hi"


@pytest.mark.asyncio
async def test_agent_loop_invokes_on_tool_call() -> None:
    llm = FakeLLM(
        responses=[
            LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
            LLMResponse(content="done", tool_calls=None),
        ]
    )
    calls: list[tuple[str, dict, str]] = []

    async def on_tool_call(name: str, args: dict, result: str) -> None:
        calls.append((name, args, result))

    result = await agent_loop(
        llm,
        messages=[{"role": "user", "content": "start"}],
        tools=[EchoTool()],
        settings=AgentLoopSettings(on_tool_call=on_tool_call),
    )
    assert result == "done"
    assert calls == [("echo", {"text": "hi"}, "echo:hi")]


@pytest.mark.asyncio
async def test_agent_loop_honors_max_iterations() -> None:
    llm = FakeLLM(
        responses=[
            LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "loop"})]),
            LLMResponse(content=None, tool_calls=[ToolCall(id="c2", name="echo", arguments={"text": "loop"})]),
            LLMResponse(content=None, tool_calls=[ToolCall(id="c3", name="echo", arguments={"text": "loop"})]),
        ]
    )
    with pytest.raises(AgentLoopLimitError):
        await agent_loop(
            llm,
            messages=[{"role": "user", "content": "go"}],
            tools=[EchoTool()],
            settings=AgentLoopSettings(max_iterations=2),
        )


@pytest.mark.asyncio
async def test_agent_loop_can_be_interrupted() -> None:
    llm = FakeLLM(responses=[LLMResponse(content="unused")])
    with pytest.raises(AgentInterruptedError):
        await agent_loop(
            llm,
            messages=[{"role": "user", "content": "go"}],
            tools=[],
            settings=AgentLoopSettings(max_iterations=2, should_stop=lambda: True),
        )


@pytest.mark.asyncio
async def test_chat_agent_streams_chunks() -> None:
    llm = FakeLLM(stream_chunks=["a", "b", "c"])
    agent = ChatAgent(llm)
    chunks: list[str] = []
    async for chunk in agent.run([{"role": "user", "content": "x"}]):
        chunks.append(chunk)
    assert "".join(chunks) == "abc"


@pytest.mark.asyncio
async def test_archive_agent_runs_loop_with_system_prompt() -> None:
    llm = FakeLLM(responses=[LLMResponse(content="archive complete")])
    agent = ArchiveAgent(llm=llm, instructions="archive instructions")
    result = await agent.run(messages=[{"role": "user", "content": "archive this"}], tools=[])
    assert result == "archive complete"


@pytest.mark.asyncio
async def test_archive_agent_run_stage() -> None:
    llm = FakeLLM(responses=[LLMResponse(content="stage complete")])
    agent = ArchiveAgent(llm=llm, instructions="default")
    stage = ArchiveStage(name="record", instructions="record stage", max_iterations=3)

    result = await agent.run_stage(
        stage=stage,
        messages=[{"role": "user", "content": "archive this"}],
        tools=[],
    )

    assert result == "stage complete"
