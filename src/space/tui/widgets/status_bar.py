"""Status bar showing tokens, cost, provider, model."""

from textual.widgets import Static


class StatusBar(Static):
    """One-line status bar."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        min-height: 1;
        border: none;
    }
    """
