from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Awaitable, Callable

from space.agent.archive import ArchiveAgent, ArchiveStage
from space.agent.base import AgentInterruptedError, AgentLoopLimitError, AgentLoopSettings, agent_loop
from space.channel.base import MessageChannel
from space.core.conversation import build_system_prompt, to_api_messages
from space.core.space import (
    create_space,
    list_history,
    list_history_files,
    list_spaces,
    load_history,
    load_space,
    save_history,
)
from space.llm.base import LLMProvider, LLMUsage

AUTOSAVE_HISTORY_ID = "_current"
from space.models import AppState, HistoryMeta, LoadedSpace, Message, Space
from space.skill.loader import load_skill
from space.store.local import LocalFileStore
from space.store.base import FileStore
from space.tool.base import Tool
from space.tool.delete_file import DeleteFileTool
from space.tool.finish_stage import FinishStageTool
from space.tool.list_files import ListFilesTool
from space.tool.read_file import ReadFileTool
from space.tool.write_file import WriteFileTool


@dataclass(slots=True, frozen=True)
class CommandResult:
    kind: str
    content: str
    interrupted: bool = False


@dataclass(slots=True, frozen=True)
class StatusData:
    tokens: int
    cost_usd: float
    space: str | None
    provider: str
    model: str


SpaceStoreFactory = Callable[[str], FileStore]
TokenCallback = Callable[[str], Awaitable[None]]
ToolCallCallback = Callable[[str, dict, str], Awaitable[None] | None]
LlmBuilder = Callable[[str, str], LLMProvider]
SettingsPersistor = Callable[[str, str], Awaitable[None] | None]
SUPPORTED_PROVIDERS = ("openrouter", "kksj")


class AppService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        spaces_store: FileStore,
        message_channel: MessageChannel | None = None,
        space_store_factory: SpaceStoreFactory | None = None,
        skills_root: Path | None = None,
        llm_builder: LlmBuilder | None = None,
        settings_persistor: SettingsPersistor | None = None,
        model: str = "openai/gpt-4o-mini",
        provider: str = "openrouter",
    ) -> None:
        self._llm = llm
        self._spaces_store = spaces_store
        self._message_channel = message_channel
        self._space_store_factory = space_store_factory or self._default_space_store_factory(spaces_store)
        self._skills_root = skills_root or (Path(__file__).resolve().parent.parent / "skill" / "skills")
        self._llm_builder = llm_builder
        self._settings_persistor = settings_persistor
        self.state = AppState(model=model, provider=provider)
        self._loaded_space: LoadedSpace | None = None
        self._models_cache: list[str] | None = None

    async def handle_input(
        self,
        text: str,
        on_token: TokenCallback | None = None,
        on_tool_call: ToolCallCallback | None = None,
        cancel: asyncio.Event | None = None,
    ) -> CommandResult:
        if text.startswith("/"):
            return await self._handle_command(text, cancel=cancel)
        return await self.chat(
            text, on_token=on_token, on_tool_call=on_tool_call, cancel=cancel
        )

    async def _handle_command(self, raw: str, cancel: asyncio.Event | None = None) -> CommandResult:
        parts = raw.strip().split(maxsplit=1)
        command = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        if command == "/space":
            if not arg:
                return CommandResult("error", "Usage: /space <name|index>")
            try:
                resolved = await self.resolve_space_target(arg)
            except ValueError as exc:
                return CommandResult("error", str(exc))
            await self.enter_space(resolved)
            return CommandResult("status", f"Entered space: {resolved}")
        if command == "/spaces":
            return CommandResult("status", await self.spaces_text())
        if command == "/providers":
            return CommandResult("status", self.providers_text())
        if command == "/provider":
            if not arg:
                return CommandResult("error", "Usage: /provider <name|index>")
            try:
                selected = await self.set_provider(arg)
            except ValueError as exc:
                return CommandResult("error", str(exc))
            return CommandResult("status", f"Provider set: {selected}")
        if command == "/models":
            provider_name = arg.strip() if arg.strip() else None
            try:
                output = await self.models_text(provider_name)
            except ValueError as exc:
                return CommandResult("error", str(exc))
            return CommandResult("status", output)
        if command == "/new":
            await self.new_conversation()
            return CommandResult("status", "Started a new conversation.")
        if command == "/exit":
            await self.exit_space()
            return CommandResult("status", "Exited space.")
        if command == "/model":
            if not arg:
                return CommandResult("error", "Usage: /model <name|index>")
            try:
                selected = await self.set_model(arg)
            except ValueError as exc:
                return CommandResult("error", str(exc))
            return CommandResult("status", f"Model set: {selected}")
        if command == "/status":
            return CommandResult("status", self.status_text())
        if command == "/help":
            return CommandResult("status", self.help_text())
        if command == "/archive":
            output = await self.archive(cancel=cancel)
            return CommandResult("status", output)
        if command == "/resume":
            output = await self.resume(arg)
            return CommandResult("status", output)
        if command == "/continue":
            output = await self.continue_latest()
            return CommandResult("status", output)
        return CommandResult("error", f"Unknown command: {command}")

    async def list_spaces(self) -> list[Space]:
        return await list_spaces(self._spaces_store)

    async def enter_space(self, name: str) -> None:
        if self.state.space is not None and self.state.conversation:
            await self._save_and_clear_conversation()
        self._reset_usage()
        space_md_path = f"{name}/SPACE.md"
        if not await self._spaces_store.exists(space_md_path):
            await create_space(name, self._spaces_store)
        self._loaded_space = await load_space(name, self._spaces_store)
        self.state.space = self._loaded_space.space
        self.state.conversation.clear()

    async def resolve_space_target(self, target: str) -> str:
        stripped = target.strip()
        if not stripped:
            raise ValueError("Space name cannot be empty.")
        if stripped.isdigit():
            spaces = await self.list_spaces()
            index = int(stripped)
            if 1 <= index <= len(spaces):
                return spaces[index - 1].name
            raise ValueError(f"Unknown space index: {target}")
        return stripped

    def _reset_usage(self) -> None:
        self.state.prompt_tokens = 0
        self.state.completion_tokens = 0
        self.state.total_tokens = 0
        self.state.total_cost_usd = 0.0

    async def new_conversation(self) -> None:
        await self._save_and_clear_conversation()
        self._reset_usage()

    async def exit_space(self) -> None:
        await self._save_and_clear_conversation()
        self.state.space = None
        self._loaded_space = None
        self._reset_usage()

    async def set_provider(self, provider: str) -> str:
        target_provider = self._resolve_provider(provider)
        if target_provider == self.state.provider:
            return target_provider
        models = await self._get_provider_models(refresh=True)
        target_model = self.state.model if self.state.model in models else (models[0] if models else self.state.model)
        await self._swap_llm(provider=target_provider, model=target_model)
        self.state.provider = target_provider
        self.state.model = target_model
        await self._persist_settings()
        return target_provider

    async def set_model(self, model: str) -> str:
        target_model = await self._resolve_model(model)
        if target_model == self.state.model:
            return target_model
        await self._swap_llm(provider=self.state.provider, model=target_model)
        self.state.model = target_model
        await self._persist_settings()
        return target_model

    def status_data(self) -> StatusData:
        return StatusData(
            tokens=self.state.total_tokens,
            cost_usd=self.state.total_cost_usd,
            space=self.state.space.name if self.state.space else None,
            provider=self.state.provider,
            model=self.state.model,
        )

    def status_text(self) -> str:
        data = self.status_data()
        turns = len(self.state.conversation)
        space_name = data.space or "none"
        cost = f"${data.cost_usd:.6f}"
        return (
            f"space={space_name} "
            f"provider={data.provider} "
            f"model={data.model} "
            f"messages={turns} "
            f"tokens={data.tokens} "
            f"cost={cost}"
        )

    @staticmethod
    def help_text() -> str:
        return (
            "Commands:\n"
            "/space <name|index>\n"
            "/spaces\n"
            "/providers\n"
            "/provider <name|index>\n"
            "/models\n"
            "/archive\n"
            "/resume [index|filename]\n"
            "/continue\n"
            "/new\n"
            "/exit\n"
            "/model <name|index>\n"
            "/status\n"
            "/help\n"
            "/quit"
        )

    def providers_text(self) -> str:
        providers = self.provider_options()
        lines = ["Providers:"]
        for idx, provider in enumerate(providers, start=1):
            marker = " (current)" if provider == self.state.provider else ""
            lines.append(f"{idx}. {provider}{marker}")
        lines.append("Use /provider <name|index>")
        return "\n".join(lines)

    def provider_options(self) -> list[str]:
        return list(SUPPORTED_PROVIDERS)

    async def spaces_text(self) -> str:
        spaces = await self.list_spaces()
        if not spaces:
            return "No spaces yet."
        current = self.state.space.name if self.state.space else None
        lines = ["Spaces:"]
        for idx, space in enumerate(spaces, start=1):
            marker = " (current)" if space.name == current else ""
            lines.append(f"{idx}. {space.name}{marker}")
        lines.append("Use /space <name|index>")
        return "\n".join(lines)

    async def models_text(self, provider: str | None = None) -> str:
        selected = self.state.provider if provider is None else self._resolve_provider(provider)
        if selected != self.state.provider:
            return f"Provider {selected} is not active. Current provider: {self.state.provider}"
        models = await self._get_provider_models(refresh=True)
        if not models:
            return f"No models available from provider: {selected}"
        lines = [f"Models for {selected}:"]
        for idx, model in enumerate(models, start=1):
            marker = " (current)" if selected == self.state.provider and model == self.state.model else ""
            lines.append(f"{idx}. {model}{marker}")
        lines.append("Use /model <name|index>")
        return "\n".join(lines)

    async def model_options(self, provider: str | None = None) -> tuple[str, list[str]]:
        selected = self.state.provider if provider is None else self._resolve_provider(provider)
        if selected != self.state.provider:
            return selected, []
        return selected, await self._get_provider_models(refresh=True)

    async def chat(
        self,
        user_input: str,
        on_token: TokenCallback | None = None,
        on_tool_call: ToolCallCallback | None = None,
        cancel: asyncio.Event | None = None,
    ) -> CommandResult:
        self.state.conversation.append(Message(role="user", content=user_input))
        prompt = build_system_prompt(self._loaded_space)
        api_messages = [{"role": "system", "content": prompt}, *to_api_messages(self.state.conversation)]

        tools: list[Tool] = []
        if self.state.space is not None:
            space_store = self._space_store_factory(self.state.space.name)
            tools = [
                ReadFileTool(space_store),
                WriteFileTool(space_store),
                DeleteFileTool(space_store),
                ListFilesTool(space_store),
            ]

        interrupted = False
        assistant_text = ""

        if tools:
            settings = AgentLoopSettings(
                max_iterations=12,
                should_stop=cancel.is_set if cancel is not None else None,
                on_usage=self._record_usage,
                on_tool_call=on_tool_call,
            )
            try:
                assistant_text = await agent_loop(
                    self._llm, api_messages, tools, settings=settings
                )
                if on_token and assistant_text:
                    await on_token(assistant_text)
            except AgentInterruptedError:
                interrupted = True
            except AgentLoopLimitError as exc:
                assistant_text = str(exc)
                if on_token:
                    await on_token(assistant_text)
        elif on_token is None:
            response = await self._llm.generate(api_messages, tools=None)
            assistant_text = response.content or ""
            self._record_usage(response.usage)
        else:
            chunks: list[str] = []
            async for token in self._llm.stream(api_messages):
                if cancel is not None and cancel.is_set():
                    interrupted = True
                    break
                chunks.append(token)
                await on_token(token)
                if cancel is not None and cancel.is_set():
                    interrupted = True
                    break
            assistant_text = "".join(chunks)
            stream_usage = getattr(self._llm, "last_usage", None)
            if isinstance(stream_usage, LLMUsage):
                self._record_usage(stream_usage)
            if not assistant_text and not interrupted:
                response = await self._llm.generate(api_messages, tools=None)
                assistant_text = response.content or ""
                self._record_usage(response.usage)
                if assistant_text:
                    await on_token(assistant_text)

        if assistant_text or not interrupted:
            self.state.conversation.append(Message(role="assistant", content=assistant_text))
        if self.state.space is not None and self.state.conversation:
            await self._save_autosave()
        return CommandResult("assistant", assistant_text, interrupted=interrupted)

    async def archive(self, cancel: asyncio.Event | None = None) -> str:
        if self.state.space is None:
            return "No active space. Use /space <name> first."
        if not self.state.conversation:
            return "Current conversation is empty, nothing to archive."
        if cancel is not None and cancel.is_set():
            return "[interrupted]"

        space_name = self.state.space.name
        space_store = self._space_store_factory(space_name)
        archive_agent = ArchiveAgent(llm=self._llm, instructions="")
        stages = self._build_archive_stages()

        tools = [
            ReadFileTool(space_store),
            WriteFileTool(space_store),
            DeleteFileTool(space_store),
            ListFilesTool(space_store),
            FinishStageTool(),
        ]

        conversation_snapshot = list(self.state.conversation)
        archive_messages = to_api_messages(conversation_snapshot)
        stage_outputs: list[str] = []
        records_before = set(await self._list_dir_entries(space_store, "records"))
        try:
            for stage in stages:
                stage_messages = list(archive_messages)
                try:
                    stage_output = await archive_agent.run_stage(
                        stage=stage,
                        messages=stage_messages,
                        tools=tools,
                        should_stop=cancel.is_set if cancel is not None else None,
                    )
                except AgentLoopLimitError as exc:
                    stage_outputs.append(f"[{stage.name}] [warn] {exc}")
                    if stage.name == "record":
                        records_after = set(await self._list_dir_entries(space_store, "records"))
                        if records_after == records_before:
                            stage_outputs.append("[warn] record stage finished without writing any file to records/")
                    continue
                clean = stage_output.strip()
                stage_outputs.append(f"[{stage.name}] {clean if clean else '(no output)'}")
                if stage.name == "record":
                    records_after = set(await self._list_dir_entries(space_store, "records"))
                    new_records = sorted(records_after - records_before)
                    if new_records:
                        stage_outputs.append(f"[record:file] {', '.join(new_records)}")
                    else:
                        stage_outputs.append("[warn] record stage finished without writing any file to records/")
                    records_before = records_after
        except AgentInterruptedError:
            return "[interrupted]"

        history_meta = HistoryMeta(
            space=space_name,
            created_at=datetime.now(timezone.utc),
            message_count=len(conversation_snapshot),
            title=None,
            record_path=None,
        )
        history_path = await save_history(conversation_snapshot, space_store, meta=history_meta)

        autosave_path = f"history/{AUTOSAVE_HISTORY_ID}.jsonl"
        if await space_store.exists(autosave_path):
            await space_store.delete(autosave_path)

        self.state.conversation.clear()
        self._loaded_space = await load_space(space_name, self._spaces_store)
        self._reset_usage()
        output_lines = stage_outputs[:]
        output_lines.append(f"Archived raw history: {history_path}")
        return "\n".join(output_lines)

    async def resume(self, arg: str) -> str:
        if self.state.space is None:
            return "No active space. Use /space <name> first."
        space_store = self._space_store_factory(self.state.space.name)
        history_items = await list_history(space_store)
        if not history_items:
            return "No history files found."

        target = arg.strip()
        if not target:
            indexed: list[str] = []
            for idx, (name, meta) in enumerate(history_items, start=1):
                if meta is None:
                    indexed.append(f"{idx}. {name}")
                    continue
                if meta.title:
                    indexed.append(f"{idx}. {name} — {meta.title} ({meta.message_count} messages)")
                else:
                    indexed.append(f"{idx}. {name} — {meta.message_count} messages")
            return "History files:\n" + "\n".join(indexed) + "\nUse /resume <index|filename> to load."

        history_files = [name for name, _ in history_items]
        resolved = self._resolve_history_target(target, history_files)
        if resolved is None:
            return f"History not found: {target}"

        loaded = await load_history(space_store, resolved)
        self.state.conversation = loaded
        return f"Loaded history: {resolved} ({len(loaded)} messages)."

    async def continue_latest(self) -> str:
        if self.state.space is None:
            return "No active space. Use /space <name> first."
        space_store = self._space_store_factory(self.state.space.name)
        autosave_name = f"{AUTOSAVE_HISTORY_ID}.jsonl"
        if await space_store.exists(f"history/{autosave_name}"):
            loaded = await load_history(space_store, AUTOSAVE_HISTORY_ID)
            self.state.conversation = loaded
            return f"Loaded autosave: {autosave_name} ({len(loaded)} messages)."
        history_files = await list_history_files(space_store)
        if not history_files:
            return "No history files found."
        latest = history_files[0]
        loaded = await load_history(space_store, latest)
        self.state.conversation = loaded
        return f"Loaded latest history: {latest} ({len(loaded)} messages)."

    async def history_options(self) -> tuple[str | None, list[str]]:
        if self.state.space is None:
            return None, []
        space_name = self.state.space.name
        space_store = self._space_store_factory(space_name)
        return space_name, await list_history_files(space_store)

    async def resume_selection_options(self) -> tuple[str | None, list[tuple[str, str]]]:
        """Returns (error_msg, options). options = [(display_label, filename), ...]."""
        if self.state.space is None:
            return "No active space. Use /space <name> first.", []
        space_store = self._space_store_factory(self.state.space.name)
        history_items = await list_history(space_store)
        if not history_items:
            return "No history files found.", []
        options: list[tuple[str, str]] = []
        for name, meta in history_items:
            if meta is None:
                options.append((name, name))
            elif meta.title:
                options.append(
                    (f"{name} — {meta.title} ({meta.message_count} msgs)", name)
                )
            else:
                options.append((f"{name} — {meta.message_count} msgs", name))
        return None, options

    def _build_archive_stages(self) -> list[ArchiveStage]:
        base = self._skills_root / "archive"
        stage_specs = [
            ("record", "record.md", 8),
            ("context", "context.md", 8),
            ("space-md", "space-md.md", 6),
        ]
        stages: list[ArchiveStage] = []
        for name, filename, max_iterations in stage_specs:
            skill = load_skill(base / filename)
            stages.append(
                ArchiveStage(
                    name=name,
                    instructions=skill.instructions,
                    max_iterations=max_iterations,
                )
            )
        return stages

    async def _swap_llm(self, provider: str, model: str) -> None:
        if self._llm_builder is None:
            return
        new_llm = self._llm_builder(provider, model)
        old_llm = self._llm
        self._llm = new_llm
        self._models_cache = None
        close_old = getattr(old_llm, "aclose", None)
        if callable(close_old):
            await close_old()

    async def _persist_settings(self) -> None:
        if self._settings_persistor is None:
            return
        outcome = self._settings_persistor(self.state.provider, self.state.model)
        if isawaitable(outcome):
            await outcome

    async def _save_autosave(self) -> None:
        """Save current conversation to history/_current.jsonl (auto-save)."""
        if self.state.space is None or not self.state.conversation:
            return
        store = self._space_store_factory(self.state.space.name)
        meta = HistoryMeta(
            space=self.state.space.name,
            created_at=datetime.now(timezone.utc),
            message_count=len(self.state.conversation),
            title=None,
            record_path=None,
        )
        await save_history(
            self.state.conversation,
            store,
            history_id=AUTOSAVE_HISTORY_ID,
            meta=meta,
        )

    async def _save_and_clear_conversation(self) -> None:
        """Save conversation to timestamped history, remove autosave, then clear."""
        if self.state.space is None or not self.state.conversation:
            self.state.conversation.clear()
            return
        store = self._space_store_factory(self.state.space.name)
        meta = HistoryMeta(
            space=self.state.space.name,
            created_at=datetime.now(timezone.utc),
            message_count=len(self.state.conversation),
            title=None,
            record_path=None,
        )
        await save_history(self.state.conversation, store, meta=meta)
        autosave_path = f"history/{AUTOSAVE_HISTORY_ID}.jsonl"
        if await store.exists(autosave_path):
            await store.delete(autosave_path)
        self.state.conversation.clear()

    def _record_usage(self, usage: LLMUsage | None) -> None:
        if usage is None:
            return
        self.state.prompt_tokens += usage.prompt_tokens
        self.state.completion_tokens += usage.completion_tokens
        self.state.total_tokens += usage.total_tokens
        if usage.cost_usd is not None:
            self.state.total_cost_usd += usage.cost_usd

    @staticmethod
    def _default_space_store_factory(spaces_store: FileStore) -> SpaceStoreFactory:
        root = getattr(spaces_store, "root", None)
        if root is None:
            raise TypeError(
                "space_store_factory is required when spaces_store has no `root` attribute "
                "(expected LocalFileStore-like store)."
            )

        def factory(space_name: str) -> FileStore:
            return LocalFileStore(root / space_name)

        return factory

    @staticmethod
    def _resolve_history_target(target: str, candidates: list[str]) -> str | None:
        stripped = target.strip()
        if stripped.isdigit():
            index = int(stripped)
            if 1 <= index <= len(candidates):
                return candidates[index - 1]
            return None
        normalized = stripped if stripped.endswith(".jsonl") else f"{stripped}.jsonl"
        return normalized if normalized in candidates else None

    def _resolve_provider(self, target: str) -> str:
        providers = self.provider_options()
        stripped = target.strip().lower()
        if stripped.isdigit():
            index = int(stripped)
            if 1 <= index <= len(providers):
                return providers[index - 1]
            raise ValueError(f"Unknown provider index: {target}")
        if stripped not in providers:
            allowed = ", ".join(providers)
            raise ValueError(f"Unknown provider: {target}. Allowed: {allowed}")
        return stripped

    async def _resolve_model(self, target: str) -> str:
        stripped = target.strip()
        models = await self._get_provider_models(refresh=True)
        if not models:
            raise ValueError(f"No models available from provider: {self.state.provider}")
        if stripped.isdigit():
            index = int(stripped)
            if 1 <= index <= len(models):
                return models[index - 1]
            raise ValueError(f"Unknown model index: {target}")
        if stripped not in models:
            raise ValueError(f"Unknown model: {target}. Use /models to list available models.")
        return stripped

    async def _get_provider_models(self, refresh: bool = False) -> list[str]:
        if not refresh and self._models_cache is not None:
            return list(self._models_cache)
        models = await self._llm.list_models()
        if models:
            self._models_cache = sorted(models)
            return list(self._models_cache)
        if self._models_cache is None:
            self._models_cache = []
        return list(self._models_cache)

    @staticmethod
    async def _list_dir_entries(store: FileStore, path: str) -> list[str]:
        if not await store.exists(path):
            return []
        try:
            return await store.list(path)
        except (FileNotFoundError, NotADirectoryError):
            return []
