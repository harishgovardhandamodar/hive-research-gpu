from __future__ import annotations

import unittest

from hive_companion.artifacts import build_explorer


def _tree() -> list[dict]:
    return [
        {"name": "2107.01994v1.pdf", "files": [{"name": "2107.01994v1.pdf", "ext": ".pdf"}]},
        {
            "name": "Notes",
            "files": [
                {"name": "digests", "files": [{"name": "digest_b.md"}, {"name": "digest_a.md"}]},
                {
                    "name": "paper_x",
                    "files": [
                        {"name": "notes.md"},
                        {"name": "figures/figure_p04_01.png"},
                        {"name": "notes.md.bak"},
                        {"name": ".hidden"},
                    ],
                },
            ],
        },
    ]


class TestExplorer(unittest.TestCase):
    def test_nested_hierarchy_with_paths(self) -> None:
        root = build_explorer(_tree())
        kids = {c["name"]: c for c in root["children"]}
        self.assertEqual(set(kids), {"digests", "paper_x"})
        px = kids["paper_x"]
        self.assertEqual(px["type"], "dir")
        by_name = {c["name"]: c for c in px["children"]}
        self.assertEqual(by_name["notes.md"]["path"], "Notes/paper_x/notes.md")
        self.assertEqual(by_name["notes.md"]["view"], "text")
        fig_dir = by_name["figures"]
        self.assertEqual(fig_dir["type"], "dir")
        fig = fig_dir["children"][0]
        self.assertEqual(fig["path"], "Notes/paper_x/figures/figure_p04_01.png")
        self.assertEqual(fig["view"], "image")

    def test_dirs_sort_first(self) -> None:
        root = build_explorer(_tree())
        kinds = [c["type"] for c in root["children"]]
        self.assertEqual(kinds, ["dir", "dir"])

    def test_junk_files_excluded(self) -> None:
        root = build_explorer(_tree())
        px = next(c for c in root["children"] if c["name"] == "paper_x")
        names = [c["name"] for c in px["children"]]
        self.assertNotIn("notes.md.bak", names)
        self.assertNotIn(".hidden", names)

    def test_file_nodes_have_no_children_key(self) -> None:
        root = build_explorer(_tree())
        digests = next(c for c in root["children"] if c["name"] == "digests")
        f = digests["children"][0]
        self.assertNotIn("children", f)

    def test_empty_tree(self) -> None:
        root = build_explorer([])
        self.assertEqual(root["children"], [])


if __name__ == "__main__":
    unittest.main()
