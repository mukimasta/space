#!/usr/bin/env -S uv run python
"""Run archive E2E and print the generated content. Inspect records, context, SPACE.md."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from space.config import load_config
from space.core.app import AppService
from space.llm.openrouter import OpenRouterProvider
from space.store.local import LocalFileStore


async def main() -> None:
    config = load_config()
    if not config.api_key.strip():
        print("Error: api_key empty in ~/.space/config.json")
        return

    model = "google/gemini-3-flash-preview"
    out_dir = Path("/tmp/space-archive-inspect")
    spaces_root = out_dir / "spaces"
    spaces_root.mkdir(parents=True, exist_ok=True)

    llm = OpenRouterProvider(
        api_key=config.api_key,
        model=model,
        base_url=config.base_url,
        timeout=90.0,
    )

    store = LocalFileStore(spaces_root)
    app = AppService(llm=llm, spaces_store=store)

    try:
        print("=== Enter space ===")
        await app.handle_input("/space inspect-test")
        print("OK\n")

        print("=== Chat ===")
        await app.handle_input("我梦到了水，感觉很平静")
        await app.handle_input("水可能代表我的情绪")
        print("OK\n")

        print("=== Archive ===")
        result = await app.handle_input("/archive")
        print(result.content)
        print()

        space_store = LocalFileStore(spaces_root / "inspect-test")

        print("=== records/ ===")
        if await space_store.exists("records"):
            for name in await space_store.list("records"):
                path = f"records/{name}"
                content = await space_store.read(path)
                print(f"--- {path} ---")
                print(content)
                print()
        else:
            print("(empty)\n")

        print("=== context/ ===")
        if await space_store.exists("context"):
            for name in await space_store.list("context"):
                path = f"context/{name}"
                content = await space_store.read(path)
                print(f"--- {path} ---")
                print(content)
                print()
        else:
            print("(empty)\n")

        print("=== SPACE.md ===")
        content = await space_store.read("SPACE.md")
        print(content)
        print()

        print("=== history/ ===")
        if await space_store.exists("history"):
            for name in await space_store.list("history"):
                print(f"  {name}")
        else:
            print("(empty)")

        print(f"\nOutput dir: {out_dir}")
    finally:
        await llm.aclose()


if __name__ == "__main__":
    asyncio.run(main())
