from __future__ import annotations

import asyncio
import unittest

import httpx

from hive_companion.hive_client import HiveApiError, HiveClient
from hive_companion.kg import KGCache


def _mock(routes: dict[tuple[str, str], list[httpx.Response]]):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        queue = routes.get((request.method, request.url.path), [])
        return queue.pop(0) if queue else httpx.Response(404, text="no route")

    return httpx.MockTransport(handler), calls


class TestHiveApiErrorMethod(unittest.TestCase):
    def test_message_includes_method(self) -> None:
        err = HiveApiError("/api/add", 500, "boom", method="POST")
        self.assertTrue(str(err).startswith("POST /api/add"))
        self.assertEqual(err.method, "POST")

    def test_default_get_for_backcompat(self) -> None:
        err = HiveApiError("/api/stats", 404, "nope")
        self.assertIn("GET", str(err))


class TestKGCacheRefresh(unittest.TestCase):
    def _graph(self, label: str) -> dict:
        return {
            "nodes": [{"id": "p1", "type": "paper", "title": label}],
            "links": [],
        }

    def test_slim_refreshes_expired_cache(self) -> None:
        transport, calls = _mock(
            {("GET", "/api/graph"): [httpx.Response(200, json=self._graph("old"))]}
        )
        client = HiveClient("http://hive.test", transport=transport)
        kg = KGCache(client)
        # simulate a cache loaded long ago
        kg._graph = self._graph("stale")
        kg._loaded_at = 0.0

        slim = asyncio.run(kg.slim())

        self.assertEqual(slim["nodes"][0]["label"], "old")  # refreshed, not stale
        self.assertGreaterEqual(len(calls), 1)

    def test_slim_fresh_cache_skips_refetch(self) -> None:
        import time

        transport, calls = _mock({("GET", "/api/graph"): []})
        client = HiveClient("http://hive.test", transport=transport)
        kg = KGCache(client)
        kg._graph = self._graph("cached")
        kg._loaded_at = time.time()  # fresh

        slim = asyncio.run(kg.slim())

        self.assertEqual(slim["nodes"][0]["label"], "cached")
        self.assertEqual(len(calls), 0)

    def test_related_subgraph_fetches_before_reading(self) -> None:
        graph = {
            "nodes": [
                {"id": "p1", "type": "paper", "title": "Seed paper"},
                {"id": "c1", "type": "concept", "label": "agents"},
            ],
            "links": [{"source": "p1", "target": "c1", "relation": "related_to"}],
        }
        transport, calls = _mock({("GET", "/api/graph"): [httpx.Response(200, json=graph)]})
        client = HiveClient("http://hive.test", transport=transport)
        kg = KGCache(client)  # never warmed

        result = asyncio.run(kg.related_subgraph(["p1"]))

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["seeds"][0]["id"], "p1")
        self.assertEqual(result["concepts"][0]["label"], "agents")


if __name__ == "__main__":
    unittest.main()
