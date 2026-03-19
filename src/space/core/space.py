from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from space.models import HistoryMeta, LoadedSpace, Message, Space
from space.store.base import FileStore

SPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CONTEXT_HEADER_RE = re.compile(r"^\s*##\s+Context\b", re.IGNORECASE)
SECTION_HEADER_RE = re.compile(r"^\s*##\s+")
CONTEXT_FILE_RE = re.compile(r"(?P<filename>[A-Za-z0-9_.-]+\.md)\b", re.IGNORECASE)


def _validate_space_name(name: str) -> str:
    value = name.strip()
    if not SPACE_NAME_RE.fullmatch(value):
        raise ValueError(
            "Invalid space name. Use 1-64 chars: letters, digits, '-' or '_', "
            "and start with a letter or digit."
        )
    return value


def _default_space_md(name: str) -> str:
    return (
        f"# {name}\n\n"
        "SPACE 描述：在这里补充这个空间的氛围、节奏、风格与相处方式。\n\n"
        "## Context\n\n"
        "已有认知文档索引：\n"
    )


async def create_space(name: str, store: FileStore) -> Space:
    safe_name = _validate_space_name(name)
    base = safe_name
    await store.mkdir(base)
    await store.mkdir(f"{base}/context")
    await store.mkdir(f"{base}/records")
    await store.mkdir(f"{base}/history")

    space_md_path = f"{base}/SPACE.md"
    if not await store.exists(space_md_path):
        await store.write(space_md_path, _default_space_md(safe_name))

    return Space(name=safe_name, path=base)


async def list_spaces(store: FileStore) -> list[Space]:
    entries = await store.list("")
    found: list[Space] = []
    for name in entries:
        if await store.exists(f"{name}/SPACE.md"):
            found.append(Space(name=name, path=name))
    found.sort(key=lambda item: item.name.lower())
    return found


def _parse_context_index(space_markdown: str) -> list[str]:
    lines = space_markdown.splitlines()
    in_context = False
    ordered: list[str] = []
    seen: set[str] = set()

    for line in lines:
        if not in_context:
            if CONTEXT_HEADER_RE.match(line):
                in_context = True
            continue

        if SECTION_HEADER_RE.match(line):
            break

        match = CONTEXT_FILE_RE.search(line)
        if match is None:
            continue
        filename = match.group("filename")
        normalized = filename.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(filename)

    return ordered


async def load_space(name: str, store: FileStore) -> LoadedSpace:
    safe_name = _validate_space_name(name)
    space_md_path = f"{safe_name}/SPACE.md"
    if not await store.exists(space_md_path):
        raise FileNotFoundError(space_md_path)

    space_markdown = await store.read(space_md_path)
    contexts: dict[str, str] = {}
    context_dir = f"{safe_name}/context"
    if await store.exists(context_dir):
        entries = await store.list(context_dir)
        context_files = sorted([entry for entry in entries if entry.lower().endswith(".md")], key=str.lower)
        indexed = _parse_context_index(space_markdown)

        if indexed:
            available = {filename.lower(): filename for filename in context_files}
            ordered_files: list[str] = []
            seen_files: set[str] = set()

            for indexed_name in indexed:
                matched = available.get(indexed_name.lower())
                if matched is None:
                    continue
                normalized = matched.lower()
                if normalized in seen_files:
                    continue
                seen_files.add(normalized)
                ordered_files.append(matched)

            for filename in context_files:
                normalized = filename.lower()
                if normalized in seen_files:
                    continue
                seen_files.add(normalized)
                ordered_files.append(filename)
        else:
            ordered_files = context_files

        for filename in ordered_files:
            content = await store.read(f"{context_dir}/{filename}")
            contexts[filename] = content

    return LoadedSpace(
        space=Space(name=safe_name, path=safe_name),
        space_markdown=space_markdown,
        contexts=contexts,
    )


def _serialize_message(message: Message) -> dict[str, str]:
    return {
        "role": message.role,
        "content": message.content,
        "timestamp": message.timestamp.isoformat(),
    }


def _serialize_meta(meta: HistoryMeta) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_type": "meta",
        "space": meta.space,
        "created_at": meta.created_at.isoformat(),
        "message_count": meta.message_count,
    }
    if meta.title is not None:
        payload["title"] = meta.title
    if meta.record_path is not None:
        payload["record_path"] = meta.record_path
    return payload


def _parse_meta(row: Any) -> HistoryMeta | None:
    if not isinstance(row, dict):
        return None
    if row.get("_type") != "meta":
        return None
    space = row.get("space")
    if not isinstance(space, str) or not space.strip():
        return None
    created_at = _parse_history_timestamp(row.get("created_at"))
    message_count_raw = row.get("message_count", 0)
    if isinstance(message_count_raw, int):
        message_count = message_count_raw
    elif isinstance(message_count_raw, float):
        message_count = int(message_count_raw)
    else:
        message_count = 0
    title = row.get("title")
    if title is not None and not isinstance(title, str):
        title = str(title)
    record_path = row.get("record_path")
    if record_path is not None and not isinstance(record_path, str):
        record_path = str(record_path)
    return HistoryMeta(
        space=space,
        created_at=created_at,
        message_count=max(0, message_count),
        title=title,
        record_path=record_path,
    )


async def save_history(
    conversation: Sequence[Message],
    store: FileStore,
    history_id: str | None = None,
    meta: HistoryMeta | None = None,
) -> str:
    history_name = history_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = f"history/{history_name}.jsonl"
    lines: list[str] = []
    if meta is not None:
        lines.append(json.dumps(_serialize_meta(meta), ensure_ascii=False))
    lines.extend(json.dumps(_serialize_message(message), ensure_ascii=False) for message in conversation)
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    await store.mkdir("history")
    await store.write(path, payload)
    return path


async def list_history_files(store: FileStore, exclude_autosave: bool = True) -> list[str]:
    history_dir = "history"
    if not await store.exists(history_dir):
        return []
    entries = await store.list(history_dir)
    names = [n for n in entries if n.endswith(".jsonl")]
    if exclude_autosave:
        names = [n for n in names if n != "_current.jsonl"]
    return sorted(names, reverse=True)


async def load_history_meta(store: FileStore, history_name: str) -> HistoryMeta | None:
    name = history_name if history_name.endswith(".jsonl") else f"{history_name}.jsonl"
    payload = await store.read(f"history/{name}")
    lines = payload.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if not first:
        return None
    try:
        row = json.loads(first)
    except json.JSONDecodeError:
        return None
    return _parse_meta(row)


async def list_history(store: FileStore) -> list[tuple[str, HistoryMeta | None]]:
    files = await list_history_files(store)
    items: list[tuple[str, HistoryMeta | None]] = []
    for filename in files:
        meta = await load_history_meta(store, filename)
        items.append((filename, meta))
    return items


def _parse_history_timestamp(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


async def load_history(store: FileStore, history_name: str) -> list[Message]:
    name = history_name if history_name.endswith(".jsonl") else f"{history_name}.jsonl"
    payload = await store.read(f"history/{name}")
    messages: list[Message] = []
    for line in payload.splitlines():
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        if row.get("_type") == "meta":
            continue
        role = str(row.get("role", "user"))
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"
        content = str(row.get("content", ""))
        timestamp = _parse_history_timestamp(row.get("timestamp"))
        messages.append(Message(role=role, content=content, timestamp=timestamp))
    return messages
