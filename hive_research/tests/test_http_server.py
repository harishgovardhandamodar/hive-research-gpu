"""Integration tests for the HTTP layer (RouteHandler).

Boots a real ThreadingHTTPServer on an ephemeral port against a stub
organizer, then exercises routing, path-traversal confinement, token auth,
and pagination — the layer where both security regressions lived.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from hive_research import server as server_mod  # noqa: F401 (module import)
from hive_research.config import Config


class StubFox:
    def list_conversations(self):
        return []

    def chat(self, message, mode="rag", conversation_id=None):
        return {"answer": "ok", "mode": mode, "sources": [], "grounded": False}


class StubOrganizer:
    """Minimal organizer surface used by the routes under test."""

    def __init__(self, tmp) -> None:
        self.config = Config(tmp / "nope.yaml")
        self.fox = StubFox()
        self.pool = type("P", (), {
            "get_observed_papers": lambda self_: [
                {"arxiv_id": f"2401.{i}", "title": f"p{i}"} for i in range(7)
            ],
        })()

    def stats(self):
        return {"papers": 0}

    def graph_data(self):
        return {"nodes": [], "links": []}


class TestHTTPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hive-http-")
        # vault with one allowed file + a bait file outside the roots
        vault = Path(cls.tmp) / "data" / "vault"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("allowed content")
        secret = Path(cls.tmp) / "secret.txt"
        secret.write_text("TOP SECRET")

        org = StubOrganizer(Path(cls.tmp))
        org.config.data["directories"] = {
            "root": cls.tmp + "/data",
            "papers": cls.tmp + "/data/papers",
            "vault": cls.tmp + "/data/vault",
        }

        cls.handler_cls = type(
            "H", (server_mod.RouteHandler,), {"log_message": lambda *a: None}
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), cls.handler_cls)
        cls.httpd.daemon_threads = True
        cls.handler_cls.org = org
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, method="GET", headers=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers=headers or {}, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            return e.code, e.read().decode()

    # -- traversal confinement ----------------------------------------------

    def test_raw_serves_allowed_file(self) -> None:
        status, body = self.request("/api/raw?path=note.md")
        self.assertEqual(status, 200)
        self.assertIn("allowed content", body)

    def test_raw_blocks_absolute_path_outside_roots(self) -> None:
        status, body = self.request(f"/api/raw?path={self.tmp}/secret.txt")
        self.assertEqual(status, 404)
        self.assertNotIn("TOP SECRET", body)

    def test_raw_blocks_parent_traversal(self) -> None:
        for payload in (
            "../secret.txt",
            "..%2Fsecret.txt",
            "Notes/../../secret.txt",
            "subdir/../../../etc/passwd",
        ):
            status, _ = self.request(f"/api/raw?path={urllib.parse.quote(payload, safe='')}")
            self.assertEqual(status, 404, f"traversal succeeded: {payload}")

    def test_read_confined_too(self) -> None:
        status, _ = self.request(f"/api/read?path={self.tmp}/secret.txt")
        self.assertEqual(status, 404)

    # -- token auth -----------------------------------------------------------

    def test_token_auth_enforced_and_accepted(self) -> None:
        old = os.environ.get("HIVE_TOKEN")
        os.environ["HIVE_TOKEN"] = "s3cret"
        try:
            status, _ = self.request("/api/stats")
            self.assertEqual(status, 401)
            status, _ = self.request("/api/stats", headers={"X-Hive-Token": "wrong"})
            self.assertEqual(status, 401)
            status, _ = self.request("/api/stats", headers={"X-Hive-Token": "s3cret"})
            self.assertEqual(status, 200)
            # query-string variant also accepted
            status, _ = self.request("/api/stats?token=s3cret")
            self.assertEqual(status, 200)
        finally:
            if old is None:
                del os.environ["HIVE_TOKEN"]
            else:
                os.environ["HIVE_TOKEN"] = old

    # -- pagination ------------------------------------------------------------

    def test_pool_papers_unpaginated_by_default(self) -> None:
        status, body = self.request("/api/pool/papers")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 7)

    def test_pool_papers_pagination(self) -> None:
        status, body = self.request("/api/pool/papers?limit=3&offset=2")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 7)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["items"][0]["arxiv_id"], "2401.2")

    # -- concurrency smoke ------------------------------------------------------

    def test_parallel_requests_do_not_serialize_each_other(self) -> None:
        """With ThreadingHTTPServer, a slow handler must not block others."""
        import time

        results = []

        def slow():
            time.sleep(1.0)
            results.append("slow")

        t = threading.Thread(target=slow)
        t.start()
        time.sleep(0.1)  # ensure slow() started and is blocking
        start = time.time()
        status, _ = self.request("/api/stats")
        elapsed = time.time() - start
        t.join()
        self.assertEqual(status, 200)
        self.assertLess(elapsed, 0.9, "request blocked behind slow handler")


if __name__ == "__main__":
    unittest.main()
