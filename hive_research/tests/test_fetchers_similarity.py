from __future__ import annotations

import unittest

from hive_research.arxiv_fetcher import parse_arxiv_id
from hive_research.similarity import jaccard_tokens


class TestParseArxivId(unittest.TestCase):
    def test_plain_new_style(self) -> None:
        self.assertEqual(parse_arxiv_id("1706.03762"), "1706.03762")

    def test_with_version_stripped(self) -> None:
        # v1/v2 must dedupe to a single graph node id
        self.assertEqual(parse_arxiv_id("2401.12345v2"), "2401.12345")

    def test_from_abs_url(self) -> None:
        self.assertEqual(parse_arxiv_id("https://arxiv.org/abs/2009.13004"), "2009.13004")

    def test_old_style_with_category(self) -> None:
        self.assertEqual(parse_arxiv_id("cs/0703125"), "cs/0703125")

    def test_inside_text(self) -> None:
        self.assertEqual(parse_arxiv_id("see paper 1810.04805 for details"), "1810.04805")

    def test_no_match(self) -> None:
        self.assertIsNone(parse_arxiv_id("not a paper id"))
        self.assertIsNone(parse_arxiv_id(""))


class TestJaccard(unittest.TestCase):
    def test_identical(self) -> None:
        self.assertEqual(jaccard_tokens("alpha beta", "beta alpha"), 1.0)

    def test_disjoint(self) -> None:
        self.assertEqual(jaccard_tokens("alpha beta", "gamma delta"), 0.0)

    def test_partial_overlap(self) -> None:
        score = jaccard_tokens("multi agent system", "agent system design")
        self.assertAlmostEqual(score, 2 / 4)

    def test_empty_inputs(self) -> None:
        self.assertEqual(jaccard_tokens("", "x"), 0.0)
        self.assertEqual(jaccard_tokens("", ""), 0.0)


if __name__ == "__main__":
    unittest.main()
