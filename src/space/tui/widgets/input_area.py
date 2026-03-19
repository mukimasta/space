"""Input area with Space prefix and TextArea."""

from textual.containers import Horizontal, Vertical
from textual.widgets import Label, Static, TextArea
from textual.widget import Widget
from textual.app import ComposeResult
from textual.message import Message
from textual import on

# Commands for / completion (order preserved)
COMMANDS = [
    "/spaces",
    "/space",
    "/archive",
    "/new",
    "/resume",
    "/continue",
    "/exit",
    "/providers",
    "/provider",
    "/models",
    "/model",
    "/status",
    "/help",
    "/quit",
]

MAX_HISTORY = 100


class CompletionPanel(Static):
    """Command completion list shown above input when typing /."""

    DEFAULT_CSS = """
    CompletionPanel {
        height: auto;
        max-height: 8;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary-darken-1;
        border-title-align: left;
        background: $surface;
        color: $text;
        display: none;
    }

    CompletionPanel.visible {
        display: block;
    }
    """


class SubmitTextArea(TextArea):
    """TextArea that sends Submit on Enter (Shift+Enter inserts newline)."""

    DEFAULT_CSS = """
    SubmitTextArea {
        background: $background 0% !important;
    }
    SubmitTextArea .text-area--cursor-line,
    SubmitTextArea .text-area--cursor-gutter {
        background: $background 0% !important;
    }
    """

    class Submit(Message):
        """Posted when user presses Enter without Shift."""

    def _get_input_area(self) -> "InputArea":
        return self.app.query_one("#input-area", InputArea)

    async def _on_key(self, event) -> None:
        input_area = self._get_input_area()

        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return

        if event.key == "escape":
            if input_area.is_completion_visible():
                event.stop()
                event.prevent_default()
                input_area.hide_completion()
            return

        if input_area.is_completion_visible():
            if event.key == "up":
                event.stop()
                event.prevent_default()
                input_area.completion_prev()
                return
            if event.key == "down":
                event.stop()
                event.prevent_default()
                input_area.completion_next()
                return
            if event.key == "enter":
                event.stop()
                event.prevent_default()
                cmd = input_area.completion_select()
                if cmd is not None:
                    input_area.insert_completion(cmd)
                return

        if event.key == "up" and self.cursor_at_first_line:
            prev = input_area.history_prev()
            if prev is not None:
                event.stop()
                event.prevent_default()
                self.text = prev
                self.move_cursor(self.document.get_line_end(0))
                return
        if event.key == "down" and self.cursor_at_last_line:
            next_ = input_area.history_next()
            if next_ is not None:
                event.stop()
                event.prevent_default()
                self.text = next_
                self.move_cursor(self.document.get_line_end(self.document.line_count - 1))
                return

        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submit())
            return
        await super()._on_key(event)


class InputArea(Widget):
    """Input area: Space prefix + multi-line TextArea."""

    DEFAULT_CSS = """
    InputArea {
        height: auto;
        min-height: 1;
        border: none;
    }

    #completion-container {
        height: 0;
        min-height: 0;
        overflow: hidden;
        border: none;
        padding: 0;
        margin: 0;
    }

    #completion-container.visible {
        height: auto;
        max-height: 8;
    }

    #input-row {
        layout: horizontal;
        height: auto;
        min-height: 1;
        border: none;
    }

    #space-prefix {
        width: auto;
        min-width: 1;
        content-align: left middle;
        color: $text-muted;
        border: none;
        background: $background 0%;
    }

    #message-input {
        width: 1fr;
        height: 1;
        min-height: 1;
        max-height: 5;
        border: none !important;
        background: $background 0% !important;
    }

    /* Override TextArea internal backgrounds to follow terminal */
    #message-input,
    #message-input .text-area--cursor-line,
    #message-input .text-area--cursor-gutter {
        background: $background 0% !important;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._input_history: list[str] = []
        self._history_index = -1
        self._completion_options: list[str] = []
        self._completion_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="completion-container"):
            yield CompletionPanel("", id="completion-panel")
        with Horizontal(id="input-row"):
            yield Label("", id="space-prefix")
            yield SubmitTextArea(id="message-input", compact=True)

    def update_space_prefix(self, space_name: str | None) -> None:
        """Update the Space name prefix. Always show ❯ ; add space name when in a space."""
        prefix = self.query_one("#space-prefix", Label)
        prefix.update(f"{space_name} ❯ " if space_name else "❯ ")

    def get_text_area(self) -> TextArea:
        return self.query_one("#message-input", TextArea)

    def add_to_history(self, text: str) -> None:
        """Append sent text to input history (dedupe from last, cap at MAX_HISTORY)."""
        text = text.strip()
        if not text:
            return
        if self._input_history and self._input_history[-1] == text:
            return
        self._input_history.append(text)
        if len(self._input_history) > MAX_HISTORY:
            self._input_history.pop(0)
        self._history_index = len(self._input_history)

    def is_completion_visible(self) -> bool:
        return self.query_one("#completion-container").has_class("visible")

    def _update_completion_ui(self) -> None:
        container = self.query_one("#completion-container")
        panel = self.query_one("#completion-panel", CompletionPanel)
        if not self._completion_options:
            container.remove_class("visible")
            panel.remove_class("visible")
            return
        container.add_class("visible")
        panel.add_class("visible")
        lines: list[str] = []
        for i, cmd in enumerate(self._completion_options):
            prefix = "▸ " if i == self._completion_index else "  "
            lines.append(f"{prefix}{cmd}")
        panel.update("\n".join(lines))

    def show_completion(self, prefix: str) -> None:
        """Filter commands by prefix and show panel."""
        prefix = (prefix or "").strip().lower()
        self._completion_options = [c for c in COMMANDS if c.lower().startswith(prefix)]
        self._completion_index = 0
        self._update_completion_ui()

    def hide_completion(self) -> None:
        self._completion_options = []
        self._completion_index = 0
        self._update_completion_ui()

    def completion_prev(self) -> None:
        if not self._completion_options:
            return
        self._completion_index = (self._completion_index - 1) % len(self._completion_options)
        self._update_completion_ui()

    def completion_next(self) -> None:
        if not self._completion_options:
            return
        self._completion_index = (self._completion_index + 1) % len(self._completion_options)
        self._update_completion_ui()

    def completion_select(self) -> str | None:
        if not self._completion_options:
            return None
        return self._completion_options[self._completion_index]

    def insert_completion(self, cmd: str) -> None:
        """Replace current line (or / prefix) with selected command and hide panel."""
        text_area = self.query_one("#message-input", SubmitTextArea)
        text = text_area.text
        lines = text.split("\n")
        cursor = text_area.cursor_location
        line_idx = cursor[0]
        if line_idx < len(lines):
            line = lines[line_idx]
            if "/" in line:
                slash_pos = line.find("/")
                new_line = line[:slash_pos] + cmd
            else:
                new_line = cmd
            lines[line_idx] = new_line
            text_area.text = "\n".join(lines)
            text_area.move_cursor((line_idx, len(new_line)))
        self.hide_completion()

    def history_prev(self) -> str | None:
        if not self._input_history:
            return None
        if self._history_index <= 0:
            self._history_index = 0
            return self._input_history[0]
        self._history_index -= 1
        return self._input_history[self._history_index]

    def history_next(self) -> str | None:
        if not self._input_history:
            return None
        if self._history_index >= len(self._input_history) - 1:
            self._history_index = len(self._input_history)
            return ""
        self._history_index += 1
        return self._input_history[self._history_index]

    @on(SubmitTextArea.Changed)
    def _on_input_changed(self, _event: SubmitTextArea.Changed) -> None:
        """Update height dynamically (1-5 lines) and show/hide completion."""
        text_area = self.query_one("#message-input", SubmitTextArea)
        line_count = text_area.document.line_count
        height = min(max(1, line_count), 5)
        text_area.styles.height = height

        text = text_area.text
        first_line = text.split("\n")[0] if text else ""
        prefix = first_line.strip()
        if prefix.startswith("/") and prefix not in COMMANDS:
            self.show_completion(prefix)
        else:
            self.hide_completion()
