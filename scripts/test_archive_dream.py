#!/usr/bin/env -S uv run python
"""Test archive with dream space in ~/.space/"""
from __future__ import annotations

import asyncio
from pathlib import Path

from space.config import ensure_data_dirs, load_config
from space.core.app import AppService
from space.llm.openrouter import OpenRouterProvider
from space.store.local import LocalFileStore


async def main() -> None:
    home = ensure_data_dirs()
    config = load_config(home)
    if not config.api_key.strip():
        print("Error: api_key empty in ~/.space/config.json")
        return

    spaces_store = LocalFileStore(home / "spaces")
    llm = OpenRouterProvider(
        api_key=config.api_key,
        model="google/gemini-3-flash-preview",
        base_url=config.base_url,
        timeout=90.0,
    )

    app = AppService(llm=llm, spaces_store=spaces_store)

    try:
        print("=== /space dream ===")
        r = await app.handle_input("/space dream")
        print(r.content)

        print("\n=== Chat ===")
        await app.handle_input("昨晚梦到门，推开门是一片海")
        await app.handle_input("海很平静，我觉得很安心")

        print("\n=== /archive ===")
        r = await app.handle_input("/archive")
        print(r.content)

        dream_store = LocalFileStore(home / "spaces" / "dream")
        print("\n=== records/ ===")
        if await dream_store.exists("records"):
            for name in sorted(await dream_store.list("records"), reverse=True)[:3]:
                content = await dream_store.read(f"records/{name}")
                print(f"--- records/{name} ---")
                print(content[:500] + "..." if len(content) > 500 else content)
                print()
        else:
            print("(empty)")

        print("=== context/ ===")
        if await dream_store.exists("context"):
            for name in await dream_store.list("context"):
                content = await dream_store.read(f"context/{name}")
                print(f"--- context/{name} ---")
                print(content[:300] + "..." if len(content) > 300 else content)
                print()
        else:
            print("(empty)")

        print("=== SPACE.md (first 40 lines) ===")
        content = await dream_store.read("SPACE.md")
        print("\n".join(content.splitlines()[:40]))

        print(f"\nData dir: {home}")
    finally:
        await llm.aclose()


if __name__ == "__main__":
    asyncio.run(main())
