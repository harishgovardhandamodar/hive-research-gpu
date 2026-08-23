from __future__ import annotations

import threading
import unittest

from hive_research.clusters import _cluster_label, compute_paper_clusters, get_paper_clusters
from hive_research.graph import KnowledgeGraph
from hive_research.tests.base import TempDirTestCase, make_config


class ClusterKG(TempDirTestCase):
    def _kg_with_groups(self) -> KnowledgeGraph:
        kg = KnowledgeGraph(make_config(self.tmp), graph_id="clu")
        group_a = [
            ("2401.1", "Multi-Agent Debate Improves Reasoning"),
            ("2401.2", "Debate Among Language Agents"),
            ("2401.3", "Agent Debate Verification"),
        ]
        group_b = [
            ("2402.1", "Prompt Injection Attacks on Assistants"),
            ("2402.2", "Jailbreak Prompts and Defenses"),
            ("2402.3", "Injection Defense via Sandboxing"),
        ]
        for pid, title in group_a + group_b:
            abstract_kw = (
                "debate reasoning agents dialogue verification"
                if pid.startswith("2401")
                else "prompt injection security jailbreak sandboxing attacks"
            )
            kg.add_paper(pid, title, abstract=f"{abstract_kw} empirical study")
        # dense within-group edges
        for i in range(3):
            a = group_a[i][0]
            b = group_b[i][0]
            kg.add_edge(a, group_a[(i + 1) % 3][0], "related_to")
            kg.add_edge(b, group_b[(i + 1) % 3][0], "related_to")
        return kg


class TestComputeClusters(ClusterKG):
    def test_two_obvious_groups_found(self) -> None:
        kg = self._kg_with_groups()
        data = compute_paper_clusters(kg, algorithm="combined", threshold=0.15)
        self.assertEqual(len(data["clusters"]), 2)
        sizes = sorted(c["size"] for c in data["clusters"])
        self.assertEqual(sizes, [3, 3])
        ids = {p["id"] for p in data["clusters"][0]["papers"]}
        # no cluster mixes the two groups
        all_a = {"2401.1", "2401.2", "2401.3"}
        self.assertTrue(ids <= all_a or ids.isdisjoint(all_a))

    def test_assignment_covers_clustered_papers(self) -> None:
        kg = self._kg_with_groups()
        data = compute_paper_clusters(kg, threshold=0.15)
        clustered = {pid for c in data["clusters"] for pid in c["paper_ids"]}
        self.assertEqual(clustered, set(data["assignment"].keys()))

    def test_high_threshold_leaves_unclustered(self) -> None:
        kg = self._kg_with_groups()
        data = compute_paper_clusters(kg, threshold=0.99)
        self.assertEqual(data["clusters"], [])
        self.assertEqual(len(data["unclustered"]), 6)

    def test_labels_are_distinctive_words(self) -> None:
        kg = self._kg_with_groups()
        data = compute_paper_clusters(kg, threshold=0.15)
        labels = [c["label"] for c in data["clusters"]]
        self.assertTrue(all(len(l) > 2 for l in labels))
        self.assertNotEqual(labels[0], labels[1])

    def test_singleton_papers_stay_unclustered(self) -> None:
        kg = self._kg_with_groups()
        kg.add_paper("2499.9", "Quantum Banana Calculus", abstract="totally unrelated quantum bananas")
        data = compute_paper_clusters(kg, threshold=0.15)
        self.assertIn("2499.9", data["unclustered"])

    def test_cache_reuses_until_graph_changes(self) -> None:
        kg = self._kg_with_groups()
        d1 = get_paper_clusters(kg, threshold=0.15)
        d2 = get_paper_clusters(kg, threshold=0.15)
        self.assertIs(d1, d2)
        kg.add_paper("2500.1", "Another Debate Paper", abstract="debate debate debate agents reasoning")
        d3 = get_paper_clusters(kg, threshold=0.15)
        self.assertIsNot(d1, d3)

    def test_thread_safety_smoke(self) -> None:
        kg = self._kg_with_groups()
        results = []
        def run():
            results.append(get_paper_clusters(kg, threshold=0.15))
        ts = [threading.Thread(target=run) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(results), 6)


class TestClusterLabel(unittest.TestCase):
    def test_stopwords_and_common_corpus_words_downweighted(self) -> None:
        corpus = [
            "Multi-Agent Debate Reasoning",
            "Language Model Alignment Study",
            "Alignment Verification Methods",
        ]
        label = _cluster_label(["Language Model Alignment Study", "Alignment Verification Methods"], corpus)
        self.assertIn("Alignment", label)
        self.assertNotIn("Model", label.split(" · ")[0] if label else "")  # 'model' is common

    def test_empty_titles_fall_back(self) -> None:
        self.assertEqual(_cluster_label([], []), "Misc")


if __name__ == "__main__":
    unittest.main()
