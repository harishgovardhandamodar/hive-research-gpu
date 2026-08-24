from __future__ import annotations

import unittest

from hive_companion.artifacts import shape_artifacts


def _tree() -> list[dict]:
    return [
        {"name": "2107.01994v1.pdf", "files": [{"name": "2107.01994v1.pdf", "ext": ".pdf"}]},
        {"name": "2203.08975v2.pdf", "files": [{"name": "2203.08975v2.pdf", "ext": ".pdf"}]},
        {
            "name": "Notes",
            "files": [
                {
                    "name": "surveys",
                    "files": [{"name": "survey_20260824.md", "ext": ".md"}, {"name": "figures/x.png", "ext": ".png"}],
                },
                {"name": "digests", "files": [{"name": "digest_20260824_2017.md", "ext": ".md"}]},
                {
                    "name": "template_based_graph_clustering",
                    "files": [{"name": "notes.md", "ext": ".md"}, {"name": "notes.md.bak", "ext": ".bak"}],
                },
            ],
        },
    ]


class TestShapeArtifacts(unittest.TestCase):
    def test_groups_surveys_digests_notes_papers(self) -> None:
        out = shape_artifacts(_tree())
        groups = {g["id"]: g for g in out["groups"]}
        self.assertEqual(groups["surveys"]["total"], 2)
        survey = groups["surveys"]["files"][0]
        self.assertEqual(survey["path"], "Notes/surveys/survey_20260824.md")
        self.assertEqual(groups["digests"]["total"], 1)
        self.assertEqual(
            groups["digests"]["files"][0]["path"], "Notes/digests/digest_20260824_2017.md"
        )
        self.assertEqual(groups["papers"]["total"], 2)
        self.assertEqual(groups["papers"]["files"][0]["path"], "2107.01994v1.pdf")

    def test_note_files_carry_readable_paths(self) -> None:
        out = shape_artifacts(_tree())
        notes = next(g for g in out["groups"] if g["id"] == "notes")
        first = notes["files"][0]
        self.assertTrue(first["path"].startswith("Notes/template_based_graph_clustering/"))

    def test_empty_tree_yields_empty_groups(self) -> None:
        out = shape_artifacts([])
        for group in out["groups"]:
            self.assertEqual(group["total"], 0)

    def test_notes_capped(self) -> None:
        tree = [
            {
                "name": "Notes",
                "files": [
                    {"name": f"paper_{i:03d}", "files": [{"name": "notes.md", "ext": ".md"}]}
                    for i in range(120)
                ],
            }
        ]
        out = shape_artifacts(tree)
        notes = next(g for g in out["groups"] if g["id"] == "notes")
        self.assertLessEqual(len(notes["files"]), 80)


if __name__ == "__main__":
    unittest.main()
