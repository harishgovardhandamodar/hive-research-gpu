from __future__ import annotations

import unittest
from unittest import mock

from hive_research.parser import (
    CAPTION_PREFIX,
    content_hash,
    is_noise_image,
    pick_caption,
)
from hive_research.pipeline import PaperPipeline
from hive_research.tests.base import TempDirTestCase, make_config


class TestContentHash(unittest.TestCase):
    def test_stable_and_short(self) -> None:
        h1 = content_hash(b"same bytes")
        h2 = content_hash(b"same bytes")
        h3 = content_hash(b"other bytes")
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertEqual(len(h1), 10)


class TestNoiseFilter(unittest.TestCase):
    def test_tiny_images_are_noise(self) -> None:
        self.assertTrue(is_noise_image(10, 10, 500))
        self.assertTrue(is_noise_image(50, 400, 3000))   # narrow strip
        self.assertTrue(is_noise_image(800, 600, 1000))  # trivially small file

    def test_real_figures_pass(self) -> None:
        self.assertFalse(is_noise_image(800, 600, 50_000))
        self.assertFalse(is_noise_image(1200, 400, 20_000))

    def test_extreme_aspect_ratio_rejected(self) -> None:
        self.assertTrue(is_noise_image(4000, 100, 30_000))


def _block(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text)


class TestPickCaption(unittest.TestCase):
    RECT = (100.0, 100.0, 400.0, 300.0)

    def test_prefers_labeled_caption_below(self) -> None:
        blocks = [
            _block(120, 310, 380, 330, "some body text far below"),
            _block(120, 305, 380, 320, "Figure 2: Multi-agent reward curves."),
        ]
        cap = pick_caption(blocks, self.RECT)
        self.assertTrue(cap.startswith("Figure 2"))

    def test_table_label_recognized(self) -> None:
        blocks = [_block(120, 305, 380, 320, "Table 5: Ablation results.")]
        self.assertTrue(CAPTION_PREFIX.match("Table 5: Ablation results."))
        cap = pick_caption(blocks, self.RECT)
        self.assertIn("Table 5", cap)

    def test_closest_unlabeled_fallback(self) -> None:
        blocks = [
            _block(120, 306, 380, 340, "closest text under image"),
            _block(120, 440, 380, 460, "distant text below"),
        ]
        cap = pick_caption(blocks, self.RECT)
        self.assertEqual(cap, "closest text under image")

    def test_caption_above_within_gap(self) -> None:
        blocks = [_block(120, 70, 380, 90, "Fig. 3: Architecture diagram.")]
        cap = pick_caption(blocks, self.RECT)
        self.assertIn("Architecture", cap)

    def test_no_candidates(self) -> None:
        blocks = [_block(500, 900, 700, 920, "unrelated")]
        self.assertEqual(pick_caption(blocks, self.RECT), "")
        self.assertEqual(pick_caption([], self.RECT), "")

    def test_bytes_blocks_decoded(self) -> None:
        block_with_bytes = (120, 305, 380, 320, b"Figure 1: encoded caption.")
        cap = pick_caption([block_with_bytes], self.RECT)
        self.assertIn("encoded caption", cap)


class FakePipelineLLM:
    """Minimal LLM double for notes rendering."""

    def extract_structured(self, prompt, **kwargs):
        return {
            "tags": ["agents"],
            "summary": "s",
            "notes": "body text [FIGURE:page=1]",
            "concepts": [{"name": "swarm", "definition": "group of agents", "relation": "uses"}],
            "experiments": [{
                "name": "Main Results",
                "goal": "g", "methodology": "m", "dataset": "d",
                "setup": "s", "baselines": "b",
                "metrics": {"acc": 0.9}, "results": "r", "findings": "f",
            }],
            "limitations": "Only tested on toy environments.",
            "tldr": "Swarm coordination scales sub-linearly.",
            "reproduction": {
                "datasets": ["SMAC", "MPE"],
                "hyperparameters": "lr=3e-4, 64 agents",
                "metrics": ["win-rate"],
                "compute": "4x A100, 12h",
                "code_url": "https://github.com/example/repo",
            },
            "experiment_ideas": ["Test transfer to unseen maps"],
        }


def make_pipeline(tmp) -> PaperPipeline:
    from hive_research.llm import LLMInterface
    from hive_research.graph import KnowledgeGraph

    cfg = make_config(tmp)
    llm = FakePipelineLLM()
    kg = KnowledgeGraph(cfg, graph_id="notes-test")
    return PaperPipeline(cfg, llm, kg)


class TestNotesTemplates(TempDirTestCase):
    def _figures(self) -> list[dict]:
        return [
            {"filename": "fig1.png", "page": 1, "caption": "Figure 1: Setup."},
        ]

    def _write(self, pipeline) -> object:
        paper = mock.Mock()
        paper.title = "Swarm Coordination Study"
        paper.authors_str = "A. Fox"
        paper.published = "2024-01-01"
        return pipeline._write_notes_multi(
            "2401.99", paper, "Short summary.", ["swarms"], [{"name": "swarm", "relation": "uses"}],
            notes="method details [FIGURE:page=1]",
            experiments_list=[{"name": "Main Results", "metrics": {"acc": 0.9}, "dataset": "SMAC"}],
            figures=self._figures(),
            limitations="Toy envs only.",
            tldr="Scales sub-linearly.",
            reproduction={"datasets": ["SMAC"], "hyperparameters": "lr=3e-4", "metrics": ["win-rate"], "code_url": "https://github.com/example/repo"},
            experiment_ideas=["Transfer test"],
        )

    def test_note_contains_new_sections(self) -> None:
        pipeline = make_pipeline(self.tmp)
        path = self._write(pipeline)
        text = path.read_text()
        for section in (
            "## Limitations & Open Questions",
            "## Reproduction Checklist",
            "## Experiment Ideas (follow-ups)",
            "TL;DR** — Scales sub-linearly",
            "- Datasets: SMAC",
            "- Metrics to match: win-rate",
            "Match dataset splits",
            "[Official code]",
        ):
            self.assertIn(section, text)

    def test_guidelines_present_as_checkboxes(self) -> None:
        pipeline = make_pipeline(self.tmp)
        path = self._write(pipeline)
        text = path.read_text()
        for guideline in PaperPipeline.REPRO_GUIDELINES[:3]:
            self.assertIn(f"- [ ] {guideline}", text)

    def test_experiment_note_has_repro_scaffold(self) -> None:
        import glob

        pipeline = make_pipeline(self.tmp)
        self._write(pipeline)
        exp_files = glob.glob(str(self.tmp / "data" / "vault" / "**" / "*00-experiment.md"), recursive=True)
        self.assertEqual(len(exp_files), 1)
        content = open(exp_files[0]).read()
        for expected in (
            "status: not-started",
            "## My Reproduction Log",
            "| metric | paper | mine | run 2 | run 3 |",
            "### Checklist for this experiment",
            "Deviations from the paper setup",
        ):
            self.assertIn(expected, content)

    def test_figure_embedding_uses_relative_path(self) -> None:
        pipeline = make_pipeline(self.tmp)
        path = self._write(pipeline)
        text = path.read_text()
        self.assertIn("![Figure 1: Setup.](figures/fig1.png)", text)

    def test_frontmatter_counts(self) -> None:
        pipeline = make_pipeline(self.tmp)
        path = self._write(pipeline)
        text = path.read_text()
        self.assertIn("figures_count: 1", text)
        self.assertIn("concepts_count: 1", text)

    def test_empty_optional_fields_do_not_crash(self) -> None:
        pipeline = make_pipeline(self.tmp)
        paper = mock.Mock()
        paper.title = "Minimal"
        paper.authors_str = ""
        paper.published = ""
        path = pipeline._write_notes_multi("2402.1", paper, "", [], [])
        self.assertIsNotNone(path)
        self.assertIn("## Reproduction Checklist", path.read_text())


class TestSectionAwareContext(TempDirTestCase):
    def _pipeline(self):
        return make_pipeline(self.tmp)

    def _long_paper(self) -> str:
        intro = "1. Introduction\n" + ("We survey many loosely related prior directions. " * 400) + "\n"
        method = "2. Method\nOur approach uses multi-agent debate with verifier models.\n"
        experiments = "3. Experiments\nWe evaluate on SMAC and MPE with 5 seeds; win-rate improves 12.3% over baselines.\n"
        results = "4. Results\nGRPO achieves 87.4 win-rate vs 75.1 for the strongest baseline.\n"
        return intro + method + experiments + results

    def test_short_text_untouched(self) -> None:
        p = self._pipeline()
        self.assertEqual(p._select_analysis_context("short text"), "short text")

    def test_experiments_survive_when_intro_is_huge(self) -> None:
        p = self._pipeline()
        ctx = p._select_analysis_context(self._long_paper(), max_chars=6000)
        self.assertIn("SMAC", ctx, "Experiments section must reach the LLM")
        self.assertIn("Results", ctx)
        # intro filler should be the thing that gets cut
        self.assertLess(ctx.count("loosely related"), 100)

    def test_budget_respected(self) -> None:
        p = self._pipeline()
        ctx = p._select_analysis_context(self._long_paper(), max_chars=3000)
        self.assertLessEqual(len(ctx), 3200)


if __name__ == "__main__":
    unittest.main()
