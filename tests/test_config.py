from __future__ import annotations

import json
from pathlib import Path

from space.config import load_config, save_config


def test_load_config_creates_default_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config_path = tmp_path / "config.json"
    assert config.provider == "openrouter"
    assert config_path.exists()


def test_save_config_roundtrip(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config.api_key = "secret"
    config.provider = "openrouter"
    save_config(config, tmp_path)

    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert payload["api_key"] == "secret"
    assert payload["provider"] == "openrouter"


def test_load_config_migrates_unsupported_provider_to_openrouter(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "api_key": "x",
                "provider": "openai",
                "model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.provider == "openrouter"
