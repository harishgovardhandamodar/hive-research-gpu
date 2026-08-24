from __future__ import annotations

import os
import unittest

from hive_research.config import Config
from hive_research.llm import LLMInterface
from hive_research.tests.base import TempDirTestCase, make_config


class TestConfigDefaults(TempDirTestCase):
    def test_missing_file_uses_defaults(self) -> None:
        cfg = Config(self.tmp / "nope.yaml")
        self.assertEqual(cfg.ollama_base_url, "http://localhost:11434")
        self.assertEqual(cfg.rag_chunk_size, 512)
        self.assertEqual(cfg.server_port, 7777)

    def test_yaml_values_loaded(self) -> None:
        cfg = make_config(self.tmp)
        self.assertEqual(cfg.ollama_model, "test-large")
        self.assertEqual(cfg.rag_chunk_overlap, 8)
        self.assertEqual(str(cfg.vault_dir), str((self.tmp / "data" / "vault").resolve()))


class TestFoxConfig(TempDirTestCase):
    def test_fox_defaults_from_ollama_model(self) -> None:
        cfg = Config(self.tmp / "nope.yaml")
        self.assertEqual(cfg.fox_model, cfg.ollama_model)
        self.assertEqual(cfg.fox_max_context_chunks, 8)

    def test_fox_overrides(self) -> None:
        cfg = make_config(self.tmp)
        self.assertEqual(cfg.fox_model, "test-fox")
        self.assertEqual(cfg.fox_max_context_chunks, 4)
        self.assertEqual(cfg.fox_history_limit, 6)

    def test_env_beats_yaml(self) -> None:
        cfg = make_config(self.tmp)
        old = os.environ.get("FOX_MODEL")
        os.environ["FOX_MODEL"] = "env-model"
        try:
            self.assertEqual(cfg.fox_model, "env-model")
        finally:
            if old is None:
                del os.environ["FOX_MODEL"]
            else:
                os.environ["FOX_MODEL"] = old


class TestGpuInstanceMethod(TempDirTestCase):
    """Regression: gpu_ollama_instance must be a callable method (was a broken property)."""

    def test_returns_instance_config(self) -> None:
        cfg = Config(self.tmp / "nope.yaml")
        result = cfg.gpu_ollama_instance(0)
        self.assertIsInstance(result, dict)


class TestFeedbackConfig(TempDirTestCase):
    def test_feedback_defaults(self) -> None:
        cfg = make_config(self.tmp)
        self.assertTrue(cfg.feedback_auto_improve)
        self.assertEqual(cfg.feedback_low_rating_threshold, 2)
        self.assertIn("feedback", str(cfg.feedback_dir))


if __name__ == "__main__":
    unittest.main()


class TestEmbedBaseURL(TempDirTestCase):
    def test_default_is_empty_uses_main_url(self) -> None:
        cfg = Config(self.tmp / "nope.yaml")
        self.assertEqual(cfg.ollama_embed_base_url, "")

    def test_env_override(self) -> None:
        old = os.environ.get("OLLAMA_EMBED_BASE_URL")
        os.environ["OLLAMA_EMBED_BASE_URL"] = "http://embed-host:9999"
        try:
            cfg = Config(self.tmp / "nope.yaml")
            self.assertEqual(cfg.ollama_embed_base_url, "http://embed-host:9999")
        finally:
            if old is None:
                del os.environ["OLLAMA_EMBED_BASE_URL"]
            else:
                os.environ["OLLAMA_EMBED_BASE_URL"] = old

    def test_embed_routes_to_dedicated_instance(self) -> None:
        llm = LLMInterface(make_config(self.tmp))
        llm.embed_base_url = "http://embed-host:9999"
        captured: dict = {}

        def fake_request(endpoint, payload, retries=3, gpu_id=None, base_url_override=""):
            captured["endpoint"] = endpoint
            captured["override"] = base_url_override
            return {"embeddings": [[0.1, 0.2]]}

        llm._request = fake_request  # type: ignore[method-assign]
        self.assertEqual(llm.embed("hello"), [0.1, 0.2])
        self.assertEqual(captured["endpoint"], "embed")
        self.assertEqual(captured["override"], "http://embed-host:9999")

    def test_embed_without_override_keeps_legacy_routing(self) -> None:
        llm = LLMInterface(Config(self.tmp / "nope.yaml"))
        captured: dict = {}

        def fake_request(endpoint, payload, retries=3, gpu_id=None, base_url_override=""):
            captured["override"] = base_url_override
            return {"embedding": [1.0]}

        llm._request = fake_request  # type: ignore[method-assign]
        self.assertEqual(llm.embed("hello"), [1.0])
        self.assertEqual(captured["override"], "")

    def test_ollama_timeout_default_and_env(self) -> None:
        cfg = Config(self.tmp / "nope.yaml")
        self.assertEqual(cfg.ollama_timeout, 600)
        old = os.environ.get("OLLAMA_TIMEOUT")
        os.environ["OLLAMA_TIMEOUT"] = "900"
        try:
            self.assertEqual(Config(self.tmp / "nope.yaml").ollama_timeout, 900)
        finally:
            if old is None:
                del os.environ["OLLAMA_TIMEOUT"]
            else:
                os.environ["OLLAMA_TIMEOUT"] = old
        os.environ["OLLAMA_TIMEOUT"] = "bogus"
        self.assertEqual(Config(self.tmp / "nope.yaml").ollama_timeout, 600)
        if old is None:
            del os.environ["OLLAMA_TIMEOUT"]
        else:
            os.environ["OLLAMA_TIMEOUT"] = old
