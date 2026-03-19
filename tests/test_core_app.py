from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from space.core.app import AppService
from space.core.conversation import build_system_prompt
from space.llm.base import LLMResponse, LLMUsage
from space.channel.base import InputEvent, OutputEvent
from space.models import LoadedSpace, Space
from space.store.local import LocalFileStore


class FakeLLM:
    def __init__(
        self,
        content: str = "assistant reply",
        *,
        usage: LLMUsage | None = None,
        stream_usage: LLMUsage | None = None,
        models: list[str] | None = None,
    ) -> None:
        self._content = content
        self._usage = usage
        self._stream_usage = stream_usage
        self._models = models or ["openai/gpt-4o-mini", "openai/gpt-4o"]
        self.last_messages: list[dict[str, Any]] | None = None
        self.last_usage: LLMUsage | None = None

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.last_messages = messages
        return LLMResponse(content=self._content, tool_calls=None, usage=self._usage)

    async def stream(self, _: list[dict[str, Any]]) -> AsyncIterator[str]:
        self.last_usage = self._stream_usage
        yield self._content

    async def aclose(self) -> None:
        return None

    async def list_models(self) -> list[str]:
        return list(self._models)


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[OutputEvent] = []

    async def send(self, event: OutputEvent) -> None:
        self.sent.append(event)

    async def receive(self) -> InputEvent:
        return InputEvent(kind="confirm_response", payload={"decision": "approve"})


def test_build_system_prompt_with_contexts() -> None:
    loaded = LoadedSpace(
        space=Space(name="dreams", path="dreams"),
        space_markdown="# dreams\n\nspace body",
        contexts={"symbols.md": "water => emotion"},
    )
    prompt = build_system_prompt(loaded)
    assert "## SPACE" in prompt
    assert "symbols.md" in prompt


@pytest.mark.asyncio
async def test_app_service_space_commands_and_chat(tmp_path: Path) -> None:
    llm = FakeLLM("hello back")
    store = LocalFileStore(tmp_path / "spaces")
    app = AppService(llm=llm, spaces_store=store, message_channel=FakeChannel())

    entered = await app.handle_input("/space dreams")
    assert "Entered space" in entered.content

    status = await app.handle_input("/status")
    assert "space=dreams" in status.content

    reply = await app.handle_input("hi")
    assert reply.kind == "assistant"
    assert reply.content == "hello back"

    spaces = await app.handle_input("/spaces")
    assert "Spaces:" in spaces.content
    assert "dreams" in spaces.content

    help_result = await app.handle_input("/help")
    assert "/archive" in help_result.content

    stream_tokens: list[str] = []

    async def on_token(token: str) -> None:
        stream_tokens.append(token)

    streamed = await app.handle_input("stream test", on_token=on_token)
    assert streamed.kind == "assistant"
    assert "".join(stream_tokens) == "hello back"


@pytest.mark.asyncio
async def test_app_service_archive_saves_history_and_clears_conversation(tmp_path: Path) -> None:
    llm = FakeLLM("archive complete")
    store = LocalFileStore(tmp_path / "spaces")
    app = AppService(llm=llm, spaces_store=store, message_channel=FakeChannel())

    await app.handle_input("/space dream")
    await app.handle_input("first")
    archive = await app.handle_input("/archive")

    assert "Archived raw history:" in archive.content
    assert app.state.conversation == []

    dream_store = LocalFileStore((tmp_path / "spaces") / "dream")
    history_entries = await dream_store.list("history")
    assert len(history_entries) == 1


@pytest.mark.asyncio
async def test_autosave_and_continue(tmp_path: Path) -> None:
    llm = FakeLLM("reply")
    store = LocalFileStore(tmp_path / "spaces")
    app = AppService(llm=llm, spaces_store=store, message_channel=FakeChannel())

    await app.handle_input("/space dream")
    await app.handle_input("hello")

    dream_store = LocalFileStore((tmp_path / "spaces") / "dream")
    assert await dream_store.exists("history/_current.jsonl")

    loaded = await app.handle_input("/continue")
    assert "Loaded autosave" in loaded.content or "Loaded latest" in loaded.content
    assert len(app.state.conversation) >= 2


@pytest.mark.asyncio
async def test_new_conversation_resets_usage(tmp_path: Path) -> None:
    usage = LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_usd=0.001)
    llm = FakeLLM("reply", usage=usage)
    app = AppService(
        llm=llm,
        spaces_store=LocalFileStore(tmp_path / "spaces"),
        message_channel=FakeChannel(),
    )
    await app.handle_input("/space dream")
    await app.handle_input("first")
    assert app.state.total_tokens > 0
    assert app.state.total_cost_usd > 0

    await app.handle_input("/new")
    assert app.state.total_tokens == 0
    assert app.state.total_cost_usd == 0.0


@pytest.mark.asyncio
async def test_new_and_exit_save_history(tmp_path: Path) -> None:
    llm = FakeLLM("reply")
    store = LocalFileStore(tmp_path / "spaces")
    app = AppService(llm=llm, spaces_store=store, message_channel=FakeChannel())

    await app.handle_input("/space dream")
    await app.handle_input("hello")
    await app.handle_input("/new")

    dream_store = LocalFileStore((tmp_path / "spaces") / "dream")
    history_entries = await dream_store.list("history")
    assert len(history_entries) >= 1
    assert any(entry.endswith(".jsonl") and not entry.startswith("_") for entry in history_entries)
    assert app.state.conversation == []

    await app.handle_input("second")
    await app.handle_input("/exit")
    assert app.state.space is None
    assert app.state.conversation == []


@pytest.mark.asyncio
async def test_resume_and_continue_commands(tmp_path: Path) -> None:
    llm = FakeLLM("assistant")
    store = LocalFileStore(tmp_path / "spaces")
    app = AppService(llm=llm, spaces_store=store, message_channel=FakeChannel())

    await app.handle_input("/space dream")
    await app.handle_input("hello")
    await app.handle_input("/archive")
    await app.handle_input("second")
    await app.handle_input("/archive")

    listed = await app.handle_input("/resume")
    assert "History files:" in listed.content

    resumed = await app.handle_input("/resume 2")
    assert "Loaded history:" in resumed.content
    assert len(app.state.conversation) >= 2

    latest = await app.handle_input("/continue")
    assert "Loaded latest history:" in latest.content

    space_name, history_files = await app.history_options()
    assert space_name == "dream"
    assert history_files


@pytest.mark.asyncio
async def test_provider_and_model_commands_with_hot_swap(tmp_path: Path) -> None:
    created: list[tuple[str, str]] = []
    persisted: list[tuple[str, str]] = []
    available_models = ["openai/gpt-4o-mini", "openai/gpt-4o"]

    def builder(provider: str, model: str) -> FakeLLM:
        created.append((provider, model))
        return FakeLLM(f"{provider}:{model}", models=available_models)

    initial = FakeLLM("initial", models=available_models)
    app = AppService(
        llm=initial,
        spaces_store=LocalFileStore(tmp_path / "spaces"),
        message_channel=FakeChannel(),
        llm_builder=builder,
        settings_persistor=lambda provider, model: persisted.append((provider, model)),
        provider="openrouter",
        model="openai/gpt-4o-mini",
    )

    providers = await app.handle_input("/providers")
    assert "openrouter (current)" in providers.content

    missing_provider = await app.handle_input("/provider")
    assert missing_provider.kind == "error"
    assert "Usage: /provider <name|index>" in missing_provider.content

    switched_provider = await app.handle_input("/provider openrouter")
    assert "Provider set: openrouter" in switched_provider.content
    assert app.state.provider == "openrouter"

    listed_models = await app.handle_input("/models")
    assert "Models for openrouter:" in listed_models.content

    switched_model = await app.handle_input("/model 1")
    assert "Model set: openai/gpt-4o" in switched_model.content
    assert app.state.model == "openai/gpt-4o"

    assert ("openrouter", "openai/gpt-4o") in created
    assert ("openrouter", "openai/gpt-4o") in persisted


@pytest.mark.asyncio
async def test_space_command_supports_index_target(tmp_path: Path) -> None:
    app = AppService(
        llm=FakeLLM("ok"),
        spaces_store=LocalFileStore(tmp_path / "spaces"),
        message_channel=FakeChannel(),
    )
    await app.handle_input("/space alpha")
    await app.handle_input("/space beta")
    switched = await app.handle_input("/space 1")
    assert "Entered space: alpha" in switched.content


@pytest.mark.asyncio
async def test_status_includes_usage_and_cost(tmp_path: Path) -> None:
    usage = LLMUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18, cost_usd=0.0025)
    llm = FakeLLM("hi", usage=usage)
    app = AppService(
        llm=llm,
        spaces_store=LocalFileStore(tmp_path / "spaces"),
        message_channel=FakeChannel(),
    )

    await app.handle_input("hello")
    status = await app.handle_input("/status")
    assert "tokens=18" in status.content
    assert "cost=$0.002500" in status.content
    data = app.status_data()
    assert data.tokens == 18
    assert data.cost_usd == 0.0025


@pytest.mark.asyncio
async def test_streaming_cancel_preserves_partial_reply(tmp_path: Path) -> None:
    llm = FakeLLM("partial output")
    app = AppService(
        llm=llm,
        spaces_store=LocalFileStore(tmp_path / "spaces"),
        message_channel=FakeChannel(),
    )
    cancel = asyncio.Event()

    async def on_token(_: str) -> None:
        cancel.set()

    result = await app.handle_input("hello", on_token=on_token, cancel=cancel)

    assert result.kind == "assistant"
    assert result.interrupted is True
    assert result.content == "partial output"
    assert app.state.conversation[-1].content == "partial output"
