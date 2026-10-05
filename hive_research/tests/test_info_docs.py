"""The About-tab documentation viewer: index, rendering source, and confinement."""

from __future__ import annotations

import unittest

from hive_research import info_docs


class TestDocIndex(unittest.TestCase):
    def test_index_lists_repository_and_docs(self) -> None:
        listing = info_docs.list_docs()
        self.assertTrue(listing["available"], listing.get("reason"))
        self.assertGreater(listing["count"], 1)
        groups = {d["group"] for d in listing["docs"]}
        self.assertIn("Repository", groups)
        self.assertIn("Documentation", groups)

    def test_every_listed_doc_is_available(self) -> None:
        for d in info_docs.list_docs()["docs"]:
            self.assertTrue(d["available"], d["id"])

    def test_architecture_doc_is_served(self) -> None:
        doc = info_docs.get_doc("architecture")
        self.assertIn("Audit Ledger and Agent Swarm", doc["markdown"])
        self.assertTrue(doc["title"])


class TestDocConfinement(unittest.TestCase):
    def test_unknown_id_is_a_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            info_docs.get_doc("no-such-document")

    def test_path_traversal_cannot_reach_config(self) -> None:
        for bad in ("../config", "../../etc/passwd", "..%2fconfig.yaml",
                    "/etc/passwd", "readme/../../config"):
            with self.assertRaises(KeyError, msg=bad):
                info_docs.get_doc(bad)

    def test_non_markdown_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            info_docs.get_doc("config.yaml")


if __name__ == "__main__":
    unittest.main()
