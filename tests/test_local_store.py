from __future__ import annotations

from pathlib import Path

import pytest

from space.store.local import LocalFileStore


@pytest.mark.asyncio
async def test_read_write_roundtrip(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    await store.write("nested/note.txt", "hello")
    content = await store.read("nested/note.txt")
    assert content == "hello"


@pytest.mark.asyncio
async def test_rejects_absolute_paths(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    with pytest.raises(ValueError):
        await store.read("/etc/passwd")


@pytest.mark.asyncio
async def test_rejects_parent_traversal(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    with pytest.raises(ValueError):
        await store.write("../escape.txt", "nope")


@pytest.mark.asyncio
async def test_blocks_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    store = LocalFileStore(root)

    with pytest.raises(PermissionError):
        await store.write("linked/escape.txt", "nope")


@pytest.mark.asyncio
async def test_delete_removes_file(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    await store.write("nested/note.txt", "hello")
    await store.delete("nested/note.txt")
    assert not await store.exists("nested/note.txt")


@pytest.mark.asyncio
async def test_delete_rejects_directory(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    await store.write("dir/file.txt", "x")
    with pytest.raises(IsADirectoryError):
        await store.delete("dir")


@pytest.mark.asyncio
async def test_lists_directory_entries(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    await store.write("context/a.md", "a")
    await store.write("context/b.md", "b")
    entries = await store.list("context")
    assert entries == ["a.md", "b.md"]
