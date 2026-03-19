from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SPACE_HOME_ENV = "SPACE_HOME"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
SUPPORTED_PROVIDERS = {"openrouter", "kksj"}

DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "kksj": "",  # use KKSJ_BASE_URL env or set in config
}


@dataclass(slots=True)
class Config:
    api_key: str = ""
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL


def _default_payload() -> dict[str, Any]:
    return {
        "api_key": "",
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
    }


def get_space_home(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return base_dir.expanduser()
    override = os.getenv(SPACE_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return (Path.home() / ".space").expanduser()


def ensure_data_dirs(base_dir: Path | None = None) -> Path:
    home = get_space_home(base_dir)
    (home / "spaces").mkdir(parents=True, exist_ok=True)
    return home


def get_config_path(base_dir: Path | None = None) -> Path:
    return get_space_home(base_dir) / "config.json"


def _normalize_provider(provider: str) -> str:
    value = provider.strip().lower()
    if value not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"Unsupported provider '{provider}'. Supported values: {supported}")
    return value


def default_base_url_for_provider(provider: str) -> str:
    normalized = _normalize_provider(provider)
    return DEFAULT_BASE_URLS[normalized]


def _from_payload(payload: dict[str, Any]) -> Config:
    merged = _default_payload() | payload
    raw_provider = str(merged["provider"])
    try:
        provider = _normalize_provider(raw_provider)
        raw_base_url = str(merged["base_url"]).strip()
        base_url = raw_base_url or default_base_url_for_provider(provider)
    except ValueError:
        provider = DEFAULT_PROVIDER
        base_url = default_base_url_for_provider(provider)
    return Config(
        api_key=str(merged["api_key"]),
        provider=provider,
        model=str(merged["model"]),
        base_url=base_url,
    )


def load_config(base_dir: Path | None = None) -> Config:
    home = ensure_data_dirs(base_dir)
    path = home / "config.json"
    if not path.exists():
        default_payload = _default_payload()
        path.write_text(json.dumps(default_payload, indent=2) + "\n", encoding="utf-8")
        return _from_payload(default_payload)
    content = path.read_text(encoding="utf-8").strip()
    payload = {} if not content else json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("config.json must contain a JSON object")
    return _from_payload(payload)


def save_config(config: Config, base_dir: Path | None = None) -> Path:
    home = ensure_data_dirs(base_dir)
    path = home / "config.json"
    payload = asdict(config)
    payload["provider"] = _normalize_provider(config.provider)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
