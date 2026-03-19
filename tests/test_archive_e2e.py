"""
E2E tests for archive flow using real OpenRouter API.

Run with:
  SPACE_API_KEY=sk-xxx pytest tests/test_archive_e2e.py -v
  OPENROUTER_API_KEY=sk-xxx pytest tests/test_archive_e2e.py -v
  pytest tests/test_archive_e2e.py -v   # uses api_key from ~/.space/config.json

Exclude from default runs: pytest -m "not e2e"
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from space.config import load_config
from space.core.app import AppService
from space.llm.openrouter import OpenRouterProvider
from space.store.local import LocalFileStore


def _get_api_key() -> str:
    key = (
        os.environ.get("SPACE_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
    )
    if key:
        return key
    try:
        config = load_config()
        return config.api_key.strip() if config.api_key else ""
    except Exception:
        return ""


E2E_SKIP = not _get_api_key()


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.skipif(E2E_SKIP, reason="Set SPACE_API_KEY or OPENROUTER_API_KEY, or api_key in ~/.space/config.json")
@pytest.mark.timeout(120)
async def test_archive_e2e_writes_record_and_history(tmp_path: Path) -> None:
    """Run full archive flow with real LLM; verify record and history are created."""
    api_key = _get_api_key()
    try:
        config = load_config()
        base_url = config.base_url
    except Exception:
        base_url = "https://openrouter.ai/api/v1"
    model = "google/gemini-3-flash-preview"

    llm = OpenRouterProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=90.0,
    )

    spaces_root = tmp_path / "spaces"
    spaces_root.mkdir(parents=True)
    store = LocalFileStore(spaces_root)
    app = AppService(llm=llm, spaces_store=store)

    try:
        # Enter space
        entered = await app.handle_input("/space e2e-archive-test")
        assert "Entered space" in entered.content

        # Chat
        await app.handle_input("我梦到了水，感觉很平静")
        await app.handle_input("水可能代表我的情绪")

        # Archive
        archive_result = await app.handle_input("/archive")

        assert "Archived raw history:" in archive_result.content
        assert app.state.conversation == []

        # Verify history
        dream_store = LocalFileStore(spaces_root / "e2e-archive-test")
        history_entries = await dream_store.list("history")
        assert len(history_entries) >= 1, "history/ should have at least one .jsonl"

        # Verify record and context (gemini-3-flash + tool_choice=required)
        records = await dream_store.list("records") if await dream_store.exists("records") else []
        assert len(records) >= 1, "records/ should have at least one .md file"
        assert all(f.endswith(".md") for f in records), "records should be .md files"
    finally:
        await llm.aclose()
