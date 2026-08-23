from __future__ import annotations

import os
import unittest

from hive_research.config import Config
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
