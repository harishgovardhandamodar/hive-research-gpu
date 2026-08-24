"""Environment-driven settings for the companion backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    hive_api_url: str = field(default_factory=lambda: _get("HIVE_API_URL", "http://127.0.0.1:7777"))
    hive_token: str = field(default_factory=lambda: _get("HIVE_TOKEN", ""))
    data_dir: Path = field(
        default_factory=lambda: Path(_get("COMPANION_DATA_DIR", "./data/companion")).expanduser()
    )
    host: str = field(default_factory=lambda: _get("COMPANION_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_get("COMPANION_PORT", "8001")))

    llm_base_url: str = field(default_factory=lambda: _get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ideation_base_url: str = field(default_factory=lambda: _get("OLLAMA_IDEATION_URL", ""))
    llm_model: str = field(default_factory=lambda: _get("OLLAMA_MODEL", "qwen3.6:latest"))
    llm_fast_model: str = field(default_factory=lambda: _get("OLLAMA_FAST_MODEL", "llama3.2:3b"))

    proactive_interval_s: int = field(default_factory=lambda: int(_get("COMPANION_PROACTIVE_INTERVAL", "300")))
    approval_timeout_s: int = field(default_factory=lambda: int(_get("COMPANION_APPROVAL_TIMEOUT", "1800")))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
