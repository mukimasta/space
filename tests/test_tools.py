from __future__ import annotations

import json
from pathlib import Path

import pytest

from space.channel.base import InputEvent, OutputEvent
from space.store.local import LocalFileStore
from space.tool.confirm import ConfirmTool
from space.tool.delete_file import DeleteFileTool
from space.tool.list_files import ListFilesTool
from space.tool.read_file import ReadFileTool
from space.tool.run_agent import RunAgentTool
from space.tool.write_file import WriteFileTool


class FakeChannel:
    def __init__(self, response: InputEvent) -> None:
        self._response = response
        self.sent: list[OutputEvent] = []

    async def send(self, event: OutputEvent) -> None:
        self.sent.append(event)

    async def receive(self) -> InputEvent:
        return self._response


@pytest.mark.asyncio
async def test_file_tools_roundtrip(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    write_tool = WriteFileTool(store)
    read_tool = ReadFileTool(store)
    delete_tool = DeleteFileTool(store)
    list_tool = ListFilesTool(store)

    write_result = await write_tool.execute(path="context/a.md", content="hello")
    content = await read_tool.execute(path="context/a.md")
    listed = await list_tool.execute(path="context")

    assert "Wrote" in write_result
    assert content == "hello"
    assert json.loads(listed)["entries"] == ["a.md"]

    delete_result = await delete_tool.execute(path="context/a.md")
    assert "Deleted" in delete_result
    assert not await store.exists("context/a.md")


@pytest.mark.asyncio
async def test_confirm_tool_uses_channel_and_parses_response() -> None:
    channel = FakeChannel(
        InputEvent(kind="confirm_response", payload={"decision": "approve", "reason": "looks good"})
    )
    tool = ConfirmTool(channel)

    result = await tool.execute(title="Update context", content="new context")
    parsed = json.loads(result)

    assert channel.sent[0].kind == "confirm_request"
    assert parsed == {"decision": "approve", "reason": "looks good"}


@pytest.mark.asyncio
async def test_run_agent_tool_delegates_to_runner() -> None:
    calls: list[tuple[str, list[dict[str, object]]]] = []

    async def runner(agent: str, messages: list[dict[str, object]]) -> str:
        calls.append((agent, messages))
        return "done"

    tool = RunAgentTool(runner)
    result = await tool.execute(agent="title", messages=[{"role": "user", "content": "hi"}])

    assert result == "done"
    assert calls == [("title", [{"role": "user", "content": "hi"}])]
