from __future__ import annotations

import asyncio
import unittest

from hive_companion.hive_client import HiveApiError, HiveClient
from hive_companion.tools import ToolRegistry

from hive_companion.tests.base import TempDirTestCase


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.content = b"x" if json_data is not None else b""


class TestToolRegistry(TempDirTestCase):
    def test_all_tools_registered_with_specs(self) -> None:
        registry = ToolRegistry(HiveClient("http://localhost:9"))
        specs = registry.specs()
        names = {s["name"] for s in specs}
        expected = {
            "library.stats",
            "library.add_paper",
            "library.import_query",
            "rag.query",
            "survey.start",
            "improve.run",
            "pool.import_topic",
            "fox.chat",
            "digest.daily",
        }
        self.assertTrue(expected.issubset(names))
        for spec in specs:
            self.assertIn("mutates", spec)
            self.assertIn("args", spec)

    def test_mutation_flags(self) -> None:
        registry = ToolRegistry(HiveClient("http://localhost:9"))
        self.assertTrue(registry.is_mutating("library.add_paper"))
        self.assertTrue(registry.is_mutating("improve.run"))
        self.assertFalse(registry.is_mutating("library.stats"))
        self.assertFalse(registry.is_mutating("fox.chat"))

    def test_execute_unknown_tool(self) -> None:
        registry = ToolRegistry(HiveClient("http://localhost:9"))
        result = asyncio.run(registry.execute("nope", {}))
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown tool", result["error"])

    def test_execute_filters_undeclared_args(self) -> None:
        class FakeClient:
            async def stats(self):
                return {"papers": 1}

        registry = ToolRegistry.__new__(ToolRegistry)
        registry.client = FakeClient()
        registry._tools = {}
        registry._register_all()
        result = asyncio.run(registry.execute("library.stats", {"bogus": 1}))
        self.assertEqual(result["status"], "ok")

    def test_hive_error_wrapped(self) -> None:
        class FailingClient:
            async def stats(self):
                raise HiveApiError("/api/stats", 500, "boom")

        registry = ToolRegistry.__new__(ToolRegistry)
        registry.client = FailingClient()
        registry._tools = {}
        registry._register_all()
        result = asyncio.run(registry.execute("library.stats", {}))
        self.assertEqual(result["status"], "error")
        self.assertIn("/api/stats", result["error"])

    def test_shrink_caps_large_lists(self) -> None:
        from hive_companion.tools import _shrink

        big = list(range(100))
        out = _shrink({"items": big})
        self.assertEqual(out["items"]["total"], 100)
        self.assertTrue(out["items"]["truncated"])
        self.assertEqual(len(_shrink(big)["items"]), 20)


if __name__ == "__main__":
    unittest.main()
