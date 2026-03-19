"""Modal screens for selection and input."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual import on


class SelectionScreen(ModalScreen[str | None]):
    """Modal screen with OptionList for single selection. Esc cancels (dismisses None)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "app.quit", "Quit"),
    ]

    def __init__(
        self,
        title: str,
        options: list[str] | None = None,
        options_pairs: list[tuple[str, str]] | None = None,
        current: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        if options_pairs is not None:
            self._pairs: list[tuple[str, str]] = options_pairs
        else:
            opts = options or []
            self._pairs = [(o, o) for o in opts]
        self._current = current

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="selection-title")
        opt_list = OptionList(id="selection-list")
        for label, opt_id in self._pairs:
            display = f"{label} (current)" if opt_id == self._current else label
            opt_list.add_option(Option(display, id=opt_id))
        yield opt_list

    def on_mount(self) -> None:
        self.query_one("#selection-list", OptionList).focus()

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ApiKeyPromptScreen(ModalScreen[str | None]):
    """Modal screen to prompt for API key. Esc cancels (dismisses None)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "app.quit", "Quit"),
    ]

    def __init__(self, provider: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._provider = provider

    def compose(self) -> ComposeResult:
        yield Label(f"API Key for {self._provider}:", id="api-key-label")
        yield Input(
            placeholder="Enter API key...",
            password=True,
            id="api-key-input",
        )

    def on_mount(self) -> None:
        self.query_one("#api-key-input", Input).focus()

    @on(Input.Submitted)
    def _on_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RewindScreen(ModalScreen[int | None]):
    """Modal screen to rewind conversation to a previous user message. Esc cancels."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "app.quit", "Quit"),
    ]

    def __init__(self, options: list[tuple[str, int]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._options = options

    def compose(self) -> ComposeResult:
        yield Static("Rewind — Restore to the point before…", id="rewind-title")
        opt_list = OptionList(id="rewind-list")
        for label, idx in self._options:
            opt_list.add_option(Option(label, id=str(idx)))
        yield opt_list

    def on_mount(self) -> None:
        self.query_one("#rewind-list", OptionList).focus()

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)
