"""Shared helpers for the Hive Research test suite (stdlib unittest only)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from hive_research.config import Config


TEST_CONFIG = """
directories:
  root: {root}/data
  papers: {root}/data/papers
  graph: {root}/data/graph
  vault: {root}/data/vault
  feedback: {root}/data/feedback

ollama:
  base_url: http://localhost:11434
  model: test-large
  fast_model: test-fast
  embed_model: test-embed

fox:
  model: test-fox
  max_context_chunks: 4
  history_limit: 6
  grounding_min_score: 0.05

rag:
  chunk_size: 40
  chunk_overlap: 8
  top_k: 3
"""


def make_config(tmp: str | Path) -> Config:
    path = Path(tmp) / "config.yaml"
    path.write_text(TEST_CONFIG.format(root=Path(tmp).resolve()))
    return Config(path)


class FakeLLM:
    """Deterministic offline LLM double for tests."""

    def __init__(self) -> None:
        self.generated: list[str] = []
        self.embed_calls = 0

    def embed(self, text: str, model: str | None = None, gpu_id: int | None = None) -> list[float]:
        self.embed_calls += 1
        vec = [0.0] * 32
        for token in text.lower().split():
            vec[hash(token) % 32] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_parallel(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        gpu_id: int | None = None,
    ) -> str:
        self.generated.append(prompt)
        return "Fox answer citing [1]."

    def extract_structured(self, prompt: str, model: str | None = None, gpu_id: int | None = None) -> dict[str, Any]:
        return {"tags": ["agents", "alignment"]}

    def chat(self, messages: list[dict[str, str]], model: str | None = None, gpu_id: int | None = None, **kwargs: Any):
        return {"content": "ok"}


class TempDirTestCase(unittest.TestCase):
    """TestCase with a per-test temp directory cleaned up afterwards."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)
