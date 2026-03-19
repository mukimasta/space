from __future__ import annotations

from typing import Sequence

from space.llm.base import ApiMessage
from space.models import LoadedSpace, Message

DEFAULT_SYSTEM_PROMPT = (
    "You are Space Agent. Be clear, concise, and practical. "
    "When in a Space, follow its memory/context as the primary collaboration frame."
)


def build_system_prompt(space: LoadedSpace | None) -> str:
    if space is None:
        return DEFAULT_SYSTEM_PROMPT

    lines = [
        DEFAULT_SYSTEM_PROMPT,
        "",
        "## SPACE",
        space.space_markdown.strip(),
        "",
        "## TOOLS",
        "You have access to read_file(path), write_file(path, content), delete_file(path), list_files(path).",
        "Use tools ONLY when the user explicitly asks for file operations or the task clearly requires it.",
        "For simple greetings, small talk, or generic questions, reply directly without calling tools.",
        "Do NOT re-read a file you have already read in this conversation.",
    ]
    if space.contexts:
        lines.append("")
        lines.append("## CONTEXT")
        for filename, content in space.contexts.items():
            lines.append(f"### {filename}")
            lines.append(content.strip())
            lines.append("")
    return "\n".join(lines).strip()


def to_api_messages(conversation: Sequence[Message]) -> list[ApiMessage]:
    return [{"role": message.role, "content": message.content} for message in conversation]
