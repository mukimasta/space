from __future__ import annotations

import asyncio
from collections.abc import Callable

from space.channel.stdio import StdioChannel
from space.core.app import AppService
from space.llm.base import LLMProvider
from space.llm.kksj import KKSJProvider
from space.llm.openrouter import OpenRouterProvider
from space.store.local import LocalFileStore
from space.tui.app import SpaceApp

from .config import Config, default_base_url_for_provider, ensure_data_dirs, load_config, save_config


def _build_provider(config_provider: str, api_key: str, model: str, base_url: str):
    if config_provider == "openrouter":
        return OpenRouterProvider(api_key=api_key, model=model, base_url=base_url)
    if config_provider == "kksj":
        import os

        kksj_key = (os.getenv("KKSJ_API_KEY") or "").strip() or api_key
        kksj_url = (base_url or "").strip() or (os.getenv("KKSJ_BASE_URL") or "").strip()
        kksj_model = (
            (model or "").strip()
            or (os.getenv("KKSJ_MODEL") or "gemini-3-flash-preview").strip()
        )
        return KKSJProvider(api_key=kksj_key, model=kksj_model, base_url=kksj_url)
    raise ValueError(f"Unsupported provider: {config_provider}")


def _build_provider_builder(config: Config, resolve_base_url: Callable[[str], str]) -> Callable[[str, str], LLMProvider]:
    def builder(provider: str, model: str) -> LLMProvider:
        resolved_base_url = resolve_base_url(provider)
        return _build_provider(provider, config.api_key, model, resolved_base_url)

    return builder


def main() -> None:
    """CLI entrypoint used by `uv run space`."""
    home = ensure_data_dirs()
    config = load_config(home)
    if not config.api_key.strip():
        print(
            "[warn] config.json 中 `api_key` 为空。聊天/归档请求会失败。"
            "请先在 ~/.space/config.json 或 $SPACE_HOME/config.json 中填写。"
        )

    llm = _build_provider(config.provider, config.api_key, config.model, config.base_url)
    provider_builder = _build_provider_builder(
        config,
        lambda provider: config.base_url if provider == config.provider else default_base_url_for_provider(provider),
    )
    spaces_store = LocalFileStore(home / "spaces")
    channel = StdioChannel()

    async def persist_settings(provider: str, model: str) -> None:
        if provider != config.provider:
            config.base_url = default_base_url_for_provider(provider)
        config.provider = provider
        config.model = model
        save_config(config, home)

    app_service = AppService(
        llm=llm,
        spaces_store=spaces_store,
        message_channel=channel,
        llm_builder=provider_builder,
        settings_persistor=persist_settings,
        model=config.model,
        provider=config.provider,
    )

    app = SpaceApp(app_service=app_service, config=config, save_config=save_config, home=home)
    try:
        app.run()
    finally:
        asyncio.run(llm.aclose())
