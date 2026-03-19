"""Message display area."""

from textual.containers import ScrollableContainer
from textual.widget import Widget


class MessageArea(ScrollableContainer):
    """Scrollable area for chat messages."""

    DEFAULT_CSS = """
    MessageArea {
        height: 1fr;
        border: none;
        overflow-y: auto;
    }
    """
