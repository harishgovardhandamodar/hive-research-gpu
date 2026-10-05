"""Environment-driven settings for the companion backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Same default as the main app: the fox-services gateway on axiom-1, speaking
# the Ollama native API. Matches compose and config.yaml so the companion does
# not quietly bypass the gateway's attribution and accounting when run bare.
_DEFAULT_GATEWAY_URL = "http://axiom-1.tailb61a66.ts.net:8210"
_DEFAULT_MODEL = "qwen3.8:27b"


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

    llm_base_url: str = field(default_factory=lambda: _get("OLLAMA_BASE_URL", _DEFAULT_GATEWAY_URL))
    ideation_base_url: str = field(default_factory=lambda: _get("OLLAMA_IDEATION_URL", ""))
    llm_model: str = field(default_factory=lambda: _get("OLLAMA_MODEL", _DEFAULT_MODEL))
    llm_fast_model: str = field(default_factory=lambda: _get("OLLAMA_FAST_MODEL", "llama3.2:3b"))
    # Attribution sent to the gateway on every call. Without a service name
    # the gateway cannot separate this app's traffic from ad-hoc curl in its
    # telemetry, which is the only place usage is accounted for.
    service_name: str = field(default_factory=lambda: _get("OLLAMA_SERVICE_NAME", "hive-research-gpu-companion"))
    requestor: str = field(default_factory=lambda: _get("OLLAMA_REQUESTOR", "agent"))
    # Must exceed the gateway's own 600s slot wait. A client that gives up
    # first abandons a slot it still holds, so the next call queues behind
    # work nobody is waiting for.
    llm_timeout_s: float = field(default_factory=lambda: float(_get("OLLAMA_TIMEOUT", "660")))

    proactive_interval_s: int = field(default_factory=lambda: int(_get("COMPANION_PROACTIVE_INTERVAL", "300")))
    approval_timeout_s: int = field(default_factory=lambda: int(_get("COMPANION_APPROVAL_TIMEOUT", "1800")))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
