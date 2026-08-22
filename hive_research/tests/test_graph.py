from __future__ import annotations

import unittest

from hive_datatype import NodeType

from hive_research.graph import KnowledgeGraph
from hive_research.tests.base import TempDirTestCase, make_config


class TestKnowledgeGraph(TempDirTestCase):
    def _kg(self, graph_id: str = "test") -> KnowledgeGraph:
        return KnowledgeGraph(make_config(self.tmp), graph_id=graph_id)

    def test_add_and_get_paper(self) -> None:
        kg = self._kg()
        node = kg.add_paper("2401.00001", "Test Paper", authors="A. Fox")
        self.assertEqual(node.type, NodeType.PAPER)
        self.assertIsNotNone(kg.get_paper("2401.00001"))

    def test_add_paper_idempotent(self) -> None:
        kg = self._kg()
        first = kg.add_paper("2401.00002", "Original Title")
        second = kg.add_paper("2401.00002", "Different Title")
        self.assertIs(first, second)
        self.assertEqual(first.label, "Original Title")
        self.assertEqual(len(kg.papers), 1)

    def test_add_concept_dedup(self) -> None:
        kg = self._kg()
        a = kg.add_concept("concept-rlhf", "RLHF", definition="x")
        b = kg.add_concept("concept-rlhf", "RLHF")
        self.assertIs(a, b)
        self.assertEqual(len(kg.concepts), 1)

    def test_edge_dedup_same_relation(self) -> None:
        kg = self._kg()
        kg.add_paper("p1", "P1")
        kg.add_concept("c1", "C1")
        e1 = kg.add_edge("p1", "c1", "mentions")
        e2 = kg.add_edge("p1", "c1", "mentions")
        self.assertIs(e1, e2)
        self.assertEqual(len(kg.edges), 1)

    def test_save_load_roundtrip(self) -> None:
        kg = self._kg()
        kg.add_paper("2401.00003", "Persisted")
        kg.add_concept("concept-x", "Concept X")
        kg.add_edge("2401.00003", "concept-x", "uses")
        kg.save()

        reloaded = self._kg()
        self.assertIsNotNone(reloaded.get_paper("2401.00003"))
        self.assertEqual(len(reloaded.edges), 1)
        self.assertEqual(reloaded.edges[0].relation, "uses")

    def test_load_drops_edges_with_invalid_refs(self) -> None:
        kg = self._kg()
        kg.add_paper("p-ok", "OK")
        kg.add_edge("p-ok", "ghost-node", "related_to")
        kg.save()

        reloaded = self._kg()
        self.assertEqual(reloaded.edges, [])

    def test_to_node_link_filters_invalid_links(self) -> None:
        kg = self._kg()
        kg.add_paper("p1", "P1")
        kg.add_concept("c1", "C1")
        kg.add_edge("p1", "c1", "uses")
        data = kg.to_node_link()
        ids = {n["id"] for n in data["nodes"]}
        for link in data["links"]:
            self.assertIn(link["source"], ids)
            self.assertIn(link["target"], ids)


if __name__ == "__main__":
    unittest.main()
