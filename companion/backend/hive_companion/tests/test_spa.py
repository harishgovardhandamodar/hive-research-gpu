from __future__ import annotations

import unittest
from typing import Any

from fastapi.testclient import TestClient

from hive_companion import main as main_mod


class _NoRaiseLifespan:
    """TestClient context that skips real startup/shutdown side effects."""

    def __enter__(self) -> TestClient:
        self._client = TestClient(main_mod.app)
        return self._client

    def __exit__(self, *args: Any) -> None:
        self._client.close()


class TestSpaRoutes(unittest.TestCase):
    def test_root_serves_built_index_or_fallback(self) -> None:
        with _NoRaiseLifespan() as client:
            resp = client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("<", resp.text[:20])
            self.assertIn("Fox Companion", resp.text)

    def test_unknown_api_path_is_json_404_not_html(self) -> None:
        with _NoRaiseLifespan() as client:
            resp = client.get("/api/does-not-exist")
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(resp.headers["content-type"], "application/json")

    def test_unknown_frontend_path_serves_spa_or_fallback(self) -> None:
        with _NoRaiseLifespan() as client:
            resp = client.get("/some/client/route")
            self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
