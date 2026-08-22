from __future__ import annotations

import unittest

from hive_research.domains import (
    DOMAIN_PRESETS,
    all_topics,
    get_domain,
    list_domains,
    topics_for_domain,
    validate_presets,
)


class TestDomainPresets(unittest.TestCase):
    def test_presets_are_structurally_valid(self) -> None:
        self.assertEqual(validate_presets(), [])

    def test_expected_domains_present(self) -> None:
        ids = {p["id"] for p in DOMAIN_PRESETS}
        for expected in ("agents", "multiagent", "swarms", "alignment", "llm-security", "agentic-security"):
            self.assertIn(expected, ids)

    def test_get_domain_unknown_returns_none(self) -> None:
        self.assertIsNone(get_domain("does-not-exist"))

    def test_list_domains_is_light(self) -> None:
        domains = list_domains()
        self.assertEqual(len(domains), len(DOMAIN_PRESETS))
        for d in domains:
            self.assertNotIn("topics", d)
            self.assertIn("topic_count", d)

    def test_topics_for_domain(self) -> None:
        topics = topics_for_domain("agents")
        self.assertTrue(topics)
        for t in topics:
            self.assertIn("name", t)
            self.assertIn("query", t)
            self.assertTrue(t["query"].strip())

    def test_all_topics_unique_names(self) -> None:
        names = [t["name"] for t in all_topics()]
        self.assertEqual(len(names), len(set(names)))

    def test_target_fields_covered(self) -> None:
        queries = " ".join(t["query"] for t in all_topics()).lower()
        for keyword in ("agent", "alignment", "security", "swarm", "reinforcement"):
            self.assertIn(keyword, queries)


if __name__ == "__main__":
    unittest.main()
