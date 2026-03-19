from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from space.core.space import (
    _parse_context_index,
    create_space,
    list_history,
    list_history_files,
    list_spaces,
    load_history,
    load_history_meta,
    load_space,
    save_history,
)
from space.models import HistoryMeta, Message
from space.store.local import LocalFileStore


@pytest.mark.asyncio
async def test_create_and_load_space(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "spaces")
    await create_space("dreams", store)
    await store.write("dreams/context/symbols.md", "# symbols")

    loaded = await load_space("dreams", store)
    assert loaded.space.name == "dreams"
    assert "Context" in loaded.space_markdown
    assert loaded.contexts == {"symbols.md": "# symbols"}


@pytest.mark.asyncio
async def test_list_spaces_filters_valid_entries(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "spaces")
    await create_space("work", store)
    await store.mkdir("scratch")
    spaces = await list_spaces(store)
    assert [space.name for space in spaces] == ["work"]


@pytest.mark.asyncio
async def test_save_history_as_jsonl(tmp_path: Path) -> None:
    space_store = LocalFileStore(tmp_path / "spaces" / "dreams")
    messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ]

    path = await save_history(messages, space_store, history_id="20260304-demo")
    payload = await space_store.read(path)

    assert path == "history/20260304-demo.jsonl"
    assert '"role": "user"' in payload
    assert '"role": "assistant"' in payload


@pytest.mark.asyncio
async def test_list_and_load_history(tmp_path: Path) -> None:
    space_store = LocalFileStore(tmp_path / "spaces" / "dreams")
    messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    ]
    await save_history(messages, space_store, history_id="20260304-a")
    await save_history(messages, space_store, history_id="20260304-b")

    history_files = await list_history_files(space_store)
    assert history_files == ["20260304-b.jsonl", "20260304-a.jsonl"]

    loaded = await load_history(space_store, "20260304-a.jsonl")
    assert [msg.role for msg in loaded] == ["user", "assistant"]


def test_parse_context_index_extracts_declared_order() -> None:
    markdown = (
        "# demo\n\n"
        "## Context\n\n"
        "- beta.md — second\n"
        "- alpha.md — first\n"
        "- [gamma.md](context/gamma.md)\n"
        "\n## Notes\n\n"
        "- unrelated\n"
    )
    assert _parse_context_index(markdown) == ["beta.md", "alpha.md", "gamma.md"]


@pytest.mark.asyncio
async def test_load_space_respects_context_index_and_appends_unlisted(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "spaces")
    await create_space("ordered", store)

    await store.write(
        "ordered/SPACE.md",
        "# ordered\n\n## Context\n\n- beta.md — second\n- alpha.md — first\n",
    )
    await store.write("ordered/context/alpha.md", "alpha")
    await store.write("ordered/context/beta.md", "beta")
    await store.write("ordered/context/gamma.md", "gamma")

    loaded = await load_space("ordered", store)
    assert list(loaded.contexts.keys()) == ["beta.md", "alpha.md", "gamma.md"]


@pytest.mark.asyncio
async def test_save_and_load_history_with_metadata(tmp_path: Path) -> None:
    space_store = LocalFileStore(tmp_path / "spaces" / "dreams")
    messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ]
    meta = HistoryMeta(
        space="dreams",
        created_at=datetime(2026, 3, 4, 8, 30, tzinfo=timezone.utc),
        message_count=2,
        title="Dream Check-in",
        record_path="records/20260304-dream-check-in.md",
    )

    path = await save_history(messages, space_store, history_id="20260304-meta", meta=meta)
    payload = await space_store.read(path)

    first_line = payload.splitlines()[0]
    assert '"_type": "meta"' in first_line

    loaded_messages = await load_history(space_store, "20260304-meta")
    assert [msg.role for msg in loaded_messages] == ["user", "assistant"]

    loaded_meta = await load_history_meta(space_store, "20260304-meta")
    assert loaded_meta is not None
    assert loaded_meta.space == "dreams"
    assert loaded_meta.message_count == 2
    assert loaded_meta.title == "Dream Check-in"
    assert loaded_meta.record_path == "records/20260304-dream-check-in.md"

    listed = await list_history(space_store)
    assert listed[0][0] == "20260304-meta.jsonl"
    assert listed[0][1] is not None
    assert listed[0][1].title == "Dream Check-in"


@pytest.mark.asyncio
async def test_load_history_meta_returns_none_for_old_format(tmp_path: Path) -> None:
    space_store = LocalFileStore(tmp_path / "spaces" / "dreams")
    messages = [
        Message(role="user", content="legacy"),
        Message(role="assistant", content="format"),
    ]
    await save_history(messages, space_store, history_id="20260304-legacy")

    loaded_messages = await load_history(space_store, "20260304-legacy")
    assert [msg.content for msg in loaded_messages] == ["legacy", "format"]

    loaded_meta = await load_history_meta(space_store, "20260304-legacy")
    assert loaded_meta is None
