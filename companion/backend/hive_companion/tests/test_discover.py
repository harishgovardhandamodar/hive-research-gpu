from __future__ import annotations

import unittest

from hive_companion.discover import join_note_paths, shape_pool_paper, vault_to_viewer_path


class TestVaultPath(unittest.TestCase):
    def test_converts_hive_note_path(self) -> None:
        self.assertEqual(
            vault_to_viewer_path("data/vault/paper_x/00_notes.md"),
            "Notes/paper_x/00_notes.md",
        )

    def test_passthrough_and_none(self) -> None:
        self.assertEqual(vault_to_viewer_path("Notes/a/b.md"), "Notes/a/b.md")
        self.assertIsNone(vault_to_viewer_path(None))
        self.assertIsNone(vault_to_viewer_path(""))


class TestShapes(unittest.TestCase):
    def test_pool_paper_trimmed(self) -> None:
        shaped = shape_pool_paper(
            {
                "arxiv_id": "2401.1v1",
                "title": "T" * 300,
                "authors_str": "A, B",
                "abstract": "abs" * 400,
                "topics": ["ai"],
                "imported": 0,
            }
        )
        self.assertLessEqual(len(shaped["title"]), 160)
        self.assertLessEqual(len(shaped["abstract"]), 420)
        self.assertFalse(shaped["imported"])

    def test_join_attaches_note_path_by_id_prefix(self) -> None:
        hits = [{"arxiv_id": "2202.09061v4", "title": "VLP", "abstract": "a"}]
        papers = [
            {"id": "2202.09061v1", "note_path": "data/vault/vlp_survey/00_notes.md"},
            {"id": "9999.99999", "note_path": "data/vault/other/notes.md"},
        ]
        joined = join_note_paths(hits, papers)
        self.assertEqual(joined[0]["note_path"], "Notes/vlp_survey/00_notes.md")

    def test_join_handles_missing(self) -> None:
        joined = join_note_paths([{"arxiv_id": "0000.00000", "title": "?", "abstract": ""}], [])
        self.assertIsNone(joined[0]["note_path"])


if __name__ == "__main__":
    unittest.main()
