"""SpaceApp - main Textual application."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.widgets import Markdown, Static
from textual import on

from space.core.app import AppService


def _format_tool_call(tool_name: str, arguments: dict, result: str) -> str:
    """Format tool call for display: ▸ name(args) → ~N tokens or N entries."""
    path = arguments.get("path", "")
    path_display = path or "."

    def is_error(r: str) -> bool:
        return r.startswith("Tool ") or "Error" in r[:30]

    if is_error(result):
        short = result[:80] + "…" if len(result) > 80 else result
        return f"▸ {tool_name}({path_display}) → {short}"

    if tool_name == "read_file":
        est = max(1, len(result) // 4)
        return f"▸ read_file({path_display}) → ~{est} tokens"
    if tool_name == "write_file":
        m = re.search(r"Wrote (\d+) chars", result)
        est = max(1, int(m.group(1)) // 4) if m else max(1, len(result) // 4)
        return f"▸ write_file({path_display}) → ~{est} tokens"
    if tool_name == "list_files":
        try:
            data = json.loads(result)
            n = len(data.get("entries", []))
            return f"▸ list_files({path_display}) → {n} entries"
        except (json.JSONDecodeError, TypeError):
            est = max(1, len(result) // 4)
            return f"▸ list_files({path_display}) → ~{est} tokens"
    if tool_name == "delete_file":
        return f"▸ delete_file({path_display}) → deleted"
    est = max(1, len(result) // 4)
    return f"▸ {tool_name}({path_display}) → ~{est} tokens"
from space.tui.screens import ApiKeyPromptScreen, RewindScreen, SelectionScreen
from space.tui.widgets import InputArea, MessageArea, StatusBar
from space.tui.widgets.input_area import SubmitTextArea

if TYPE_CHECKING:
    from space.config import Config


class SpaceApp(App[None]):
    """Space Agent TUI."""

    TITLE = "Space Agent"
    SUB_TITLE = "v0.1.0"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("meta+c", "copy_selection", "Copy"),
        ("escape", "escape_action", "Interrupt/Rewind"),
    ]

    CSS_PATH = Path(__file__).parent / "app.css"

    def __init__(
        self,
        app_service: AppService,
        *,
        config: Config | None = None,
        save_config: Callable[[Config, Path], Path] | None = None,
        home: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(ansi_color=True, **kwargs)
        self._app_service = app_service
        self._config = config
        self._save_config = save_config
        self._home = home
        self._streaming_cancel: asyncio.Event | None = None

    def compose(self) -> ComposeResult:
        yield MessageArea(id="message-area")
        yield Static("─" * 200, id="separator-top")
        yield InputArea(id="input-area")
        yield Static("─" * 200, id="separator-bottom")
        yield StatusBar("", id="status-bar")

    def on_mount(self) -> None:
        self._refresh_status()
        self._refresh_space_prefix()
        self.query_one("#input-area", InputArea).get_text_area().focus()

    def _refresh_status(self) -> None:
        data = self._app_service.status_data()
        tokens_str = f"{data.tokens / 1000:.1f}k" if data.tokens >= 1000 else str(data.tokens)
        cost_str = f"${data.cost_usd:.2f}"
        left = f"{tokens_str} tokens · {cost_str}"
        right = f"{data.provider} · {data.model}"
        status = f"{left}  {right}"
        self.query_one("#status-bar", StatusBar).update(status)

    def action_escape_action(self) -> None:
        """Esc: interrupt streaming, or show Rewind to rewind conversation."""
        if self._streaming_cancel is not None:
            self._streaming_cancel.set()
            return
        self._show_rewind()

    def _show_rewind(self) -> None:
        """Show Rewind screen to truncate conversation to a previous point."""
        conv = self._app_service.state.conversation
        user_indices: list[tuple[str, int]] = []
        for i, msg in enumerate(conv):
            if msg.role == "user":
                preview = msg.content[:60] + "…" if len(msg.content) > 60 else msg.content
                preview = preview.replace("\n", " ")
                label = f"❯ {preview}"
                user_indices.append((label, i))
        if not user_indices:
            self.notify("No messages to rewind to", severity="information")
            return
        user_indices.append(("❯ (current)", len(conv)))
        self.run_worker(self._run_rewind(user_indices), exclusive=False)

    async def _run_rewind(self, options: list[tuple[str, int]]) -> None:
        selected = await self.push_screen_wait(RewindScreen(options))
        if selected is None:
            return
        conv = self._app_service.state.conversation
        if selected >= len(conv):
            return
        self._app_service.state.conversation = conv[: selected + 1]
        self._refresh_message_area_from_conversation()
        self._refresh_status()
        self.notify("Rewound conversation", severity="information")

    def _refresh_message_area_from_conversation(self) -> None:
        """Clear and re-mount message area from current conversation."""
        message_area = self.query_one("#message-area", MessageArea)
        message_area.remove_children()
        for msg in self._app_service.state.conversation:
            if msg.role == "user":
                message_area.mount(Static(f"❯ {msg.content}", classes="user-message"))
            else:
                message_area.mount(Markdown(msg.content, classes="assistant-message"))
        message_area.scroll_end(animate=False)

    def action_copy_selection(self) -> None:
        """Copy selected text to clipboard via OSC 52 (works in iTerm2, Kitty, etc.)."""
        focused = self.focused
        if focused is not None:
            selected = getattr(focused, "selected_text", "") or ""
            if isinstance(selected, str) and selected.strip():
                self.copy_to_clipboard(selected)
                self.notify(f"Copied {len(selected)} chars", severity="information")
                return
        # No selection: try copying all message area content (Static has .content)
        try:
            message_area = self.query_one("#message-area", MessageArea)
            parts: list[str] = []
            for child in message_area.children:
                content = getattr(child, "content", None) or getattr(child, "source", None)
                if isinstance(content, str) and content.strip():
                    parts.append(content.strip())
            if parts:
                text = "\n\n".join(parts)
                self.copy_to_clipboard(text)
                self.notify(f"Copied {len(text)} chars (all messages)", severity="information")
                return
        except Exception:
            pass
        self.notify("No selection to copy", severity="warning")

    def _refresh_space_prefix(self) -> None:
        input_area = self.query_one("#input-area", InputArea)
        input_area.update_space_prefix(
            self._app_service.state.space.name if self._app_service.state.space else None
        )

    @on(SubmitTextArea.Submit)
    def _on_submit(self, _event: SubmitTextArea.Submit) -> None:
        text_area = self.query_one("#message-input", SubmitTextArea)
        input_area = self.query_one("#input-area", InputArea)
        text = text_area.text.strip()
        text_area.text = ""
        if not text:
            return
        input_area.add_to_history(text)
        if text == "/quit":
            self.exit()
            return
        self.run_worker(self._handle_send(text), exclusive=True)

    async def _handle_send(self, text: str) -> None:
        message_area = self.query_one("#message-area", MessageArea)
        message_area.mount(Static(f"❯ {text}", classes="user-message"))
        message_area.scroll_end(animate=False)
        try:
            if text.strip().startswith("/"):
                handled = await self._handle_selection_commands(message_area, text)
                if not handled:
                    result = await self._app_service.handle_input(text)
                    self._mount_result(message_area, result)
            else:
                await self._handle_chat_streaming(message_area, text)
        except Exception as exc:
            message_area.mount(Static(f"[error] {type(exc).__name__}: {exc}", classes="error"))
            message_area.scroll_end(animate=False)
        self._refresh_status()

    async def _handle_selection_commands(self, message_area: MessageArea, text: str) -> bool:
        """Handle /spaces, /providers, /models with selection panels. Returns True if handled."""
        if text.strip() == "/spaces":
            spaces = await self._app_service.list_spaces()
            if not spaces:
                message_area.mount(Static("No spaces yet.", classes="status-message"))
                message_area.scroll_end(animate=False)
                return True
            current = self._app_service.state.space.name if self._app_service.state.space else None
            options = [s.name for s in spaces]
            selected = await self.push_screen_wait(
                SelectionScreen("Select Space", options, current=current)
            )
            if selected:
                await self._app_service.enter_space(selected)
                message_area.mount(Static(f"Entered space: {selected}", classes="status-message"))
                message_area.scroll_end(animate=False)
                self._refresh_space_prefix()
            return True

        if text.strip() == "/providers":
            providers = self._app_service.provider_options()
            current = self._app_service.state.provider
            selected = await self.push_screen_wait(
                SelectionScreen("Select Provider", providers, current=current)
            )
            if selected:
                need_key = (
                    self._config is not None
                    and self._save_config is not None
                    and self._home is not None
                    and not self._config.api_key.strip()
                )
                if need_key:
                    api_key = await self.push_screen_wait(ApiKeyPromptScreen(selected))
                    if not api_key:
                        return True  # user cancelled api key prompt
                    self._config.api_key = api_key
                    self._save_config(self._config, self._home)
                try:
                    await self._app_service.set_provider(selected)
                    message_area.mount(Static(f"Provider set: {selected}", classes="status-message"))
                    message_area.scroll_end(animate=False)
                except ValueError as exc:
                    message_area.mount(Static(str(exc), classes="error"))
                    message_area.scroll_end(animate=False)
            return True

        if text.strip().startswith("/models"):
            arg = text.strip().split(maxsplit=1)[1] if len(text.strip().split()) > 1 else ""
            provider_name = arg.strip() or None
            try:
                provider, models = await self._app_service.model_options(provider_name)
            except ValueError as exc:
                message_area.mount(Static(str(exc), classes="error"))
                message_area.scroll_end(animate=False)
                return True
            if not models:
                message_area.mount(
                    Static(f"No models available from provider: {provider}", classes="status-message")
                )
                message_area.scroll_end(animate=False)
                return True
            current = self._app_service.state.model if self._app_service.state.provider == provider else None
            selected = await self.push_screen_wait(
                SelectionScreen(f"Select Model ({provider})", models, current=current)
            )
            if selected:
                try:
                    await self._app_service.set_model(selected)
                    message_area.mount(Static(f"Model set: {selected}", classes="status-message"))
                    message_area.scroll_end(animate=False)
                except ValueError as exc:
                    message_area.mount(Static(str(exc), classes="error"))
                    message_area.scroll_end(animate=False)
            return True

        if text.strip().startswith("/resume"):
            err, options = await self._app_service.resume_selection_options()
            if err:
                message_area.mount(Static(err, classes="error"))
                message_area.scroll_end(animate=False)
                return True
            if not options:
                message_area.mount(Static("No history files found.", classes="status-message"))
                message_area.scroll_end(animate=False)
                return True
            selected = await self.push_screen_wait(
                SelectionScreen("Select History", options_pairs=options)
            )
            if selected:
                result = await self._app_service.handle_input(f"/resume {selected}")
                self._mount_result(message_area, result)
                if result.kind == "status" and "Loaded history" in (result.content or ""):
                    self._refresh_message_area_from_conversation()
            return True

        return False

    def _mount_result(self, message_area: MessageArea, result) -> None:
        """Mount command/status result or final assistant message."""
        content = result.content or ""
        if result.kind == "assistant":
            message_area.mount(Markdown(content, classes="assistant-message"))
        else:
            message_area.mount(Static(content, classes="status-message"))
        message_area.scroll_end(animate=False)

    async def _handle_chat_streaming(self, message_area: MessageArea, text: str):
        """Handle chat with streaming and Markdown rendering. Esc interrupts."""
        cancel = asyncio.Event()
        self._streaming_cancel = cancel
        try:
            buffer: list[str] = []
            last_update_ms = 0.0
            THROTTLE_MS = 80

            markdown_widget = Markdown("", classes="assistant-message")
            message_area.mount(markdown_widget)
            message_area.scroll_end(animate=False)

            async def on_tool_call(tool_name: str, arguments: dict, result: str) -> None:
                line = _format_tool_call(tool_name, arguments, result)
                static = Static(line, classes="tool-call")
                message_area.mount(static, before=markdown_widget)
                message_area.scroll_end(animate=False)

            async def on_token(token: str) -> None:
                buffer.append(token)
                nonlocal last_update_ms
                now_ms = time.monotonic() * 1000
                if now_ms - last_update_ms >= THROTTLE_MS:
                    await markdown_widget.update("".join(buffer))
                    last_update_ms = now_ms
                    message_area.scroll_end(animate=False)

            result = await self._app_service.handle_input(
                text,
                on_token=on_token,
                on_tool_call=on_tool_call,
                cancel=cancel,
            )
            full_content = "".join(buffer)
            if full_content:
                await markdown_widget.update(full_content)
            if result.interrupted:
                await markdown_widget.update(full_content + "\n\n[interrupted]")
            message_area.scroll_end(animate=False)
            return result
        finally:
            self._streaming_cancel = None
