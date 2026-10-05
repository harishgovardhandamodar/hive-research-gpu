from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config.yaml")

# Where inference goes when nothing overrides it: the fox-services gateway on
# axiom-1 (2x RTX 5080 peer, over Tailscale), which speaks the Ollama native
# API. Kept in step with the shipped config.yaml on purpose -- config.yaml is
# loaded by relative path, so a run started from another directory falls
# through to these values. "Where does inference go" should have one answer
# regardless of working directory.
_DEFAULT_GATEWAY_URL = "http://axiom-1.tailb61a66.ts.net:8210"
_DEFAULT_MODEL = "qwen3.8:27b"


class Config:
    def __init__(self, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
        self.data: dict[str, Any] = {}
        if Path(path).exists():
            with open(path) as f:
                self.data = yaml.safe_load(f) or {}

    def _get(self, *keys: str, default: Any = None) -> Any:
        d = self.data
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k, {})
            else:
                return default
        return d if d != {} else default

    @property
    def root_dir(self) -> Path:
        return Path(self._get("directories", "root", default="./data"))

    @property
    def papers_dir(self) -> Path:
        return Path(self._get("directories", "papers", default="./data/papers"))

    @property
    def graph_dir(self) -> Path:
        return Path(self._get("directories", "graph", default="./data/graph"))

    @property
    def vault_dir(self) -> Path:
        return Path(self._get("directories", "vault", default="./data/vault"))

    @property
    def arxiv_max_results(self) -> int:
        return int(self._get("arxiv", "max_results", default=10))

    @property
    def arxiv_download_pdf(self) -> bool:
        return bool(self._get("arxiv", "download_pdf", default=True))

    @property
    def ollama_base_url(self) -> str:
        """Gateway base URL. Ollama-native, so a bare Ollama URL also works."""
        return os.environ.get("OLLAMA_BASE_URL") or str(
            self._get("ollama", "base_url", default=_DEFAULT_GATEWAY_URL)
        )

    @property
    def ollama_model(self) -> str:
        """Main analysis model. The gateway may serve a different one instead;
        the served name is recorded per note rather than assumed."""
        return os.environ.get("OLLAMA_MODEL") or str(
            self._get("ollama", "model", default=_DEFAULT_MODEL)
        )

    @property
    def ollama_fast_model(self) -> str:
        return os.environ.get("OLLAMA_FAST_MODEL") or str(
            self._get("ollama", "fast_model", default="llama3.2:3b")
        )

    @property
    def ollama_embed_model(self) -> str:
        return os.environ.get("OLLAMA_EMBED_MODEL") or str(
            self._get("ollama", "embed_model", default="nomic-embed-text")
        )

    @property
    def ollama_embed_base_url(self) -> str:
        """Optional separate base URL for embeddings. Empty means 'same as chat'.

        The original reason for splitting was that a large chat model sharing
        an instance with an embedder starves it. Against the gateway that is
        no longer the trade-off: the gateway already keeps per-model slots and
        prefers an already-loaded model, so embeddings queued on it neither
        wait behind a 27B load nor stall a chat call. Leaving this empty keeps
        every inference row in the gateway's telemetry; pointing it at a bare
        Ollama (:11434) makes embeddings invisible there.
        """
        return os.environ.get("OLLAMA_EMBED_BASE_URL") or str(
            self._get("ollama", "embed_base_url", default="")
        )

    @property
    def ollama_service_name(self) -> str:
        """Attribution name reported to the gateway on every request.

        The gateway groups all inference telemetry by this string. Left
        unset, every call from this app is filed as ``gateway-unknown`` and
        cannot be told apart from ad-hoc curl traffic.
        """
        return os.environ.get("OLLAMA_SERVICE_NAME") or str(
            self._get("ollama", "service_name", default="hive-research-gpu")
        )

    @property
    def ollama_requestor(self) -> str:
        """Whether calls are a person asking, or a pipeline step nobody asked for."""
        return os.environ.get("OLLAMA_REQUESTOR") or str(
            self._get("ollama", "requestor", default="subagent")
        )

    @property
    def ollama_timeout(self) -> int:
        """Per-request LLM read timeout in seconds.

        Thinking models routinely generate for minutes on long sections;
        the historical 180s default aborts them mid-handler.
        """
        try:
            return int(os.environ.get("OLLAMA_TIMEOUT") or self._get("ollama", "timeout", default=600))
        except ValueError:
            return 600

    @property
    def ollama_direct_gpu_routing(self) -> bool:
        """Pin per-GPU requests straight to that GPU's Ollama, bypassing the gateway.

        Off by default because it silently costs three things: the call is
        unattributed in the gateway's telemetry, it returns no
        ``X-Served-Model`` so provenance is unknowable, and it skips the
        managed pool entirely. Enable it only for a box deliberately running
        several Ollama instances outside the gateway's control.
        """
        raw = os.environ.get("OLLAMA_DIRECT_GPU_ROUTING")
        if raw is None:
            raw = self._get("ollama", "direct_gpu_routing", default="false")
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    def resolve_model(self, model: str | None) -> str | None:
        if not model or model == "large":
            return self.ollama_model
        if model == "fast":
            return self.ollama_fast_model
        return model

    @property
    def ollama_max_tokens(self) -> int:
        return int(self._get("ollama", "max_tokens", default=8192))

    @property
    def ollama_temperature(self) -> float:
        return float(self._get("ollama", "temperature", default=0.1))

    @property
    def graph_similarity_threshold(self) -> float:
        return float(self._get("graph", "similarity_threshold", default=0.85))

    @property
    def rag_chunk_size(self) -> int:
        return int(self._get("rag", "chunk_size", default=512))

    @property
    def rag_chunk_overlap(self) -> int:
        return int(self._get("rag", "chunk_overlap", default=64))

    @property
    def rag_top_k(self) -> int:
        return int(self._get("rag", "top_k", default=5))

    @property
    def server_host(self) -> str:
        return str(self._get("server", "host", default="127.0.0.1"))

    @property
    def server_port(self) -> int:
        return int(self._get("server", "port", default=7777))

    @property
    def gpu_enabled(self) -> bool:
        return bool(self._get("gpu", "enabled", default=True))

    @property
    def gpu_device_count(self) -> int:
        return int(self._get("gpu", "device_count", default=2))

    @property
    def gpu_memory_fraction(self) -> float:
        return float(self._get("gpu", "memory_fraction", default=0.95))

    @property
    def gpu_parallel_papers(self) -> int:
        return int(self._get("gpu", "parallel_papers", default=2))

    def gpu_ollama_instance(self, gpu_id: int) -> dict[str, Any]:
        key = f"gpu_{gpu_id}"
        return dict(
            self._get("gpu", "ollama_instances", key, default={})
        )

    @property
    def gpu_embedding_device(self) -> int:
        return int(self._get("gpu", "embedding_device", default=0))

    @property
    def gpu_llm_device(self) -> int:
        return int(self._get("gpu", "llm_device", default=1))

    # ---- Fox research companion -------------------------------------------

    @property
    def fox_model(self) -> str:
        env = os.environ.get("FOX_MODEL")
        if env:
            return env
        return str(
            self._get("fox", "model", default=self.ollama_model)
        )

    @property
    def fox_max_context_chunks(self) -> int:
        return int(self._get("fox", "max_context_chunks", default=8))

    @property
    def fox_history_limit(self) -> int:
        return int(self._get("fox", "history_limit", default=12))

    @property
    def fox_temperature(self) -> float:
        return float(self._get("fox", "temperature", default=0.2))

    @property
    def fox_grounding_min_score(self) -> float:
        return float(self._get("fox", "grounding_min_score", default=0.15))

    # ---- Reinforcement feedback loop ---------------------------------------

    @property
    def feedback_dir(self) -> Path:
        return Path(self._get("directories", "feedback", default=str(Path(self.root_dir) / "feedback")))

    @property
    def feedback_auto_improve(self) -> bool:
        return bool(self._get("feedback", "auto_improve", default=True))

    @property
    def feedback_low_rating_threshold(self) -> int:
        return int(self._get("feedback", "low_rating_threshold", default=2))

    @property
    def feedback_reanalyze_max(self) -> int:
        return int(self._get("feedback", "reanalyze_max", default=5))

    # ---- Research workflow --------------------------------------------------

    @property
    def digest_hours(self) -> int:
        return int(self._get("workflow", "digest_hours", default=24))

    @property
    def domain_presets_enabled(self) -> list[str]:
        raw = self._get("workflow", "domain_presets", default=None)
        if isinstance(raw, list) and raw:
            return [str(x) for x in raw]
        return []

    # ---- Agent swarm + audit ledger ----------------------------------------

    @property
    def ledger_db_path(self) -> Path:
        """Where the hash-chained audit ledger lives.

        Under ``root`` rather than beside the config: the ledger is evidence, so
        it belongs with the data it describes and should travel with a copy of
        the data directory.
        """
        raw = self._get("ledger", "db_path", default="")
        if raw:
            return Path(raw)
        return Path(self.root_dir) / "ledger.sqlite3"

    @property
    def ledger_enabled(self) -> bool:
        """The swarm is the only ingest path, so this is not a behaviour switch.

        It exists so a caller can point at a throwaway ledger (tests, a dry run)
        rather than the real one, and so ``swarm.enabled`` can be read as an
        honest statement of what is running.
        """
        return bool(self._get("ledger", "enabled", default=True))

    @property
    def swarm_budget_llm_calls(self) -> int:
        """Per-paper inference ceiling. A runaway extraction loop is stopped by
        policy in the ledger rather than by hoping the model terminates."""
        return int(self._get("swarm", "budget_llm_calls", default=12))

    @property
    def swarm_budget_minutes(self) -> float:
        return float(self._get("swarm", "budget_minutes", default=30))

    @property
    def swarm_min_grounded_ratio(self) -> float:
        """Share of extracted numeric values that must appear in the source text.

        A warning threshold rather than a gate: the check is a substring match
        against PDF-extracted text, so a legitimate paraphrase trips it. Blocking
        on a noisy signal trains people to ignore the gate.
        """
        return float(self._get("swarm", "min_grounded_ratio", default=0.5))

    @property
    def swarm_allowed_sources(self) -> list[str]:
        """Hosts the ingest may fetch from. Empty = no restriction expressed."""
        raw = self._get("swarm", "allowed_sources", default=None)
        if isinstance(raw, list) and raw:
            return [str(x).strip().lower() for x in raw]
        return []

    @property
    def swarm_fallback_enabled(self) -> bool:
        """Whether a swarm that cannot complete may fall back to the single-prompt
        path. On by default: a partial note beats no note, and the fallback is
        recorded as ``run.degraded`` so it can never be mistaken for a clean run.
        """
        return bool(self._get("swarm", "fallback_enabled", default=True))
