from __future__ import annotations

import asyncio
from pathlib import Path


class LocalFileStore:
    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _normalize_relative(self, path: str) -> Path:
        rel = Path(path)
        if rel.is_absolute():
            raise ValueError("absolute paths are not allowed")
        if any(part == ".." for part in rel.parts):
            raise ValueError("parent traversal is not allowed")
        return rel

    def _ensure_in_root(self, path: Path) -> None:
        if path != self._root and self._root not in path.parents:
            raise PermissionError(f"path escapes store root: {path}")

    def _resolve_safe(self, path: str) -> Path:
        rel = self._normalize_relative(path)
        resolved = (self._root / rel).resolve(strict=False)
        self._ensure_in_root(resolved)
        return resolved

    async def read(self, path: str) -> str:
        target = self._resolve_safe(path)
        if not await asyncio.to_thread(target.exists):
            raise FileNotFoundError(path)
        if await asyncio.to_thread(target.is_dir):
            raise IsADirectoryError(path)
        return await asyncio.to_thread(target.read_text, encoding="utf-8")

    async def write(self, path: str, content: str) -> None:
        target = self._resolve_safe(path)
        parent = target.parent
        self._ensure_in_root(parent.resolve(strict=False))
        await asyncio.to_thread(parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")

    async def delete(self, path: str) -> None:
        target = self._resolve_safe(path)
        if not await asyncio.to_thread(target.exists):
            raise FileNotFoundError(path)
        if await asyncio.to_thread(target.is_dir):
            raise IsADirectoryError(path)
        await asyncio.to_thread(target.unlink)

    async def list(self, path: str) -> list[str]:
        target = self._resolve_safe(path)
        if not await asyncio.to_thread(target.exists):
            raise FileNotFoundError(path)
        if not await asyncio.to_thread(target.is_dir):
            raise NotADirectoryError(path)

        def _iter_names() -> list[str]:
            return sorted(item.name for item in target.iterdir())

        return await asyncio.to_thread(_iter_names)

    async def exists(self, path: str) -> bool:
        target = self._resolve_safe(path)
        return await asyncio.to_thread(target.exists)

    async def mkdir(self, path: str) -> None:
        target = self._resolve_safe(path)
        self._ensure_in_root(target.parent.resolve(strict=False))
        if await asyncio.to_thread(target.exists) and not await asyncio.to_thread(target.is_dir):
            raise FileExistsError(path)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
