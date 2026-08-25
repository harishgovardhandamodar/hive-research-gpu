from __future__ import annotations

import unittest

from hive_companion.agents_catalog import CATALOG, CATEGORIES, CATALOG_BY_ID, AgentSelectionStore
from hive_companion.tests.base import TempDirTestCase


class TestCatalog(unittest.TestCase):
    def test_counts_and_categories(self) -> None:
        self.assertEqual(len(CATALOG), 15)
        self.assertEqual(set(CATEGORIES), {"ideation", "experimentation", "writing"})
        by_cat = {c: [a for a in CATALOG if a.category == c] for c in CATEGORIES}
        self.assertEqual(len(by_cat["ideation"]), 5)
        self.assertEqual(len(by_cat["experimentation"]), 5)
        self.assertEqual(len(by_cat["writing"]), 5)

    def test_fields_and_urls(self) -> None:
        for a in CATALOG:
            self.assertTrue(a.id)
            self.assertTrue(a.name)
            self.assertTrue(a.paper_url.startswith("https://arxiv.org/"))
            self.assertTrue(a.workflow)
            self.assertTrue(a.capabilities)
            self.assertIn(a.autonomy, {"approve", "tiered", "auto"})
            self.assertIn(a.id, CATALOG_BY_ID)

    def test_implemented_flag(self) -> None:
        implemented = [a for a in CATALOG if a.implemented]
        self.assertTrue(any(a.id == "ideagent" for a in implemented))


class TestSelectionStore(TempDirTestCase):
    def test_defaults(self) -> None:
        store = AgentSelectionStore(self.data_dir / "agent_selection.json")
        sel = store.get()
        self.assertIn("ideagent", sel)
        self.assertIn("pasa", sel)

    def test_set_and_persist(self) -> None:
        path = self.data_dir / "agent_selection.json"
        s1 = AgentSelectionStore(path)
        s1.set(["ai-scientist", "scisage"])
        self.assertEqual(s1.get(), ["ai-scientist", "scisage"])
        s2 = AgentSelectionStore(path)
        self.assertEqual(s2.get(), ["ai-scientist", "scisage"])

    def test_invalid_ids_dropped(self) -> None:
        store = AgentSelectionStore(self.data_dir / "agent_selection.json")
        store.set(["nope", "ideagent"])
        self.assertEqual(store.get(), ["ideagent"])

    def test_empty_falls_back_to_default(self) -> None:
        store = AgentSelectionStore(self.data_dir / "agent_selection.json")
        store.set([])
        self.assertTrue(len(store.get()) >= 1)


if __name__ == "__main__":
    unittest.main()
