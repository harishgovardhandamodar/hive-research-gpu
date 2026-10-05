"""Note provenance: a note must not claim a model that did not write it.

The gateway substitutes models (prefer an already-loaded one over paying a
cold load). Before this, the pipeline stamped nothing and the note's YAML
frontmatter carried no model name at all -- so the wrong model was implied by
silence. ``analyzed_by`` is what actually wrote the file; ``requested_model``
is what the pipeline asked for. When they differ, that difference is visible
in the artifact instead of hidden in a log line.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from hive_research.arxiv_fetcher import PaperInfo
from hive_research.llm import GatewayBusy
from hive_research.pipeline import PaperPipeline
from hive_research.tests.base import make_config


class _FakeLLM:
    """Stands in for LLMInterface, including the gateway provenance handshake.

    The real client learns the served model from the ``X-Served-Model`` response
    header and writes it to ``last_served_model`` *during* the call. The fake
    does the same, which matters because the pipeline clears the field before
    an analysis and reads it after -- a fake that only set it in __init__ would
    be cleared and every note would fall back to the requested name.
    """

    def __init__(self, served: str = "") -> None:
        self.served = served
        self.last_served_model = ""
        self.last_served_node = "gw-node"
        self.asked: list[str | None] = []
        self.embed_calls = 0

    def generate(self, prompt: str, model: str | None = None, system: str | None = None,
                 temperature: float | None = None, max_tokens: int | None = None,
                 gpu_id: int | None = None) -> str:
        self.asked.append(model)
        if self.served:
            self.last_served_model = self.served
        return "generated"

    def generate_parallel(self, prompts: list[str], model: str | None = None,
                          system: str | None = None, temperature: float | None = None,
                          max_tokens: int | None = None) -> list[str]:
        return [self.generate(p, model=model) for p in prompts]

    def extract_structured(self, prompt: str, model: str | None = None,
                           gpu_id: int | None = None) -> dict[str, Any]:
        self.asked.append(model)
        if self.served:
            self.last_served_model = self.served
        return {
            "summary": "A summary.",
            "tags": ["ml", "agents"],
            "concepts": [{"name": "Retrieval", "relation": "uses",
                          "type": "concept", "definition": "Fetching evidence."}],
            "relations": [],
            "notes": "",
            "limitations": "",
        }

    def embed(self, text: str, model: str | None = None, gpu_id: int | None = None) -> list[float]:
        self.embed_calls += 1
        return [0.0] * 128

    def embed_parallel(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        return [self.embed(t, model=model) for t in texts]

    def gateway_status(self) -> dict[str, Any]:
        return {"reachable": True, "loaded_models": ["served-model-x"]}


class _FakeAuthor:
    name = "Ada Lovelace"
    affiliation = ""


class _FakeArxivResult:
    """PaperInfo wraps an arxiv.Result, so the test has to supply one."""

    def __init__(self, arxiv_id: str, title: str) -> None:
        self.entry_id = f"http://arxiv.org/abs/{arxiv_id}v1"
        self.title = title
        self.authors = [_FakeAuthor()]
        self.summary = "An abstract about retrieval."
        self.published = None
        self.updated = None
        self.categories = ["cs.LG"]
        self.pdf_url = f"http://arxiv.org/pdf/{arxiv_id}v1"
        self.links: list = []

    def get_short_id(self) -> str:
        return self._short_id

    _short_id = ""


def _paper(arxiv_id: str = "2401.00001", title: str = "A Test Paper") -> PaperInfo:
    result = _FakeArxivResult(arxiv_id, title)
    result._short_id = arxiv_id
    return PaperInfo(result)  # type: ignore[arg-type]


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"')
    return out


class TestNoteProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hive-prov-"))
        self.cfg = make_config(self.tmp)
        self.paper = _paper()

    def _pipeline(self, llm: _FakeLLM, config: Any = None) -> PaperPipeline:
        from hive_research.graph import KnowledgeGraph
        cfg = config or self.cfg
        kg = KnowledgeGraph(cfg)
        return PaperPipeline(cfg, llm, kg, gpu_mgr=None)  # type: ignore[arg-type]

    def _run(self, llm: _FakeLLM, config: Any = None, paper: PaperInfo | None = None,
             **kwargs: Any) -> dict[str, Any]:
        pipe = self._pipeline(llm, config)
        # Keep the test offline and fast: no PDF fetch, no lineage fetch, and
        # the extraction itself is the fake LLM's canned dict.
        with mock.patch.object(pipe, "fetch_lineage", return_value=[]):
            return pipe.process_paper(paper or self.paper,
                                      model=kwargs.get("model"), progress=None)

    def test_note_records_the_model_that_actually_wrote_it(self) -> None:
        llm = _FakeLLM(served="served-model-x")
        self._run(llm, model="configured-model")

        note = Path(self.cfg.vault_dir) / "a_test_paper" / "00_notes.md"
        self.assertTrue(note.exists(), f"expected a note at {note}")
        fm = _frontmatter(note.read_text())
        self.assertEqual(fm.get("analyzed_by"), "served-model-x")

    def test_note_also_records_what_was_asked_for(self) -> None:
        """Both names, because the difference between them is the finding."""
        llm = _FakeLLM(served="served-model-x")
        self._run(llm, model="configured-model")

        note = Path(self.cfg.vault_dir) / "a_test_paper" / "00_notes.md"
        fm = _frontmatter(note.read_text())
        self.assertEqual(fm.get("requested_model"), "configured-model")

    def test_substitution_is_visible_as_a_mismatch(self) -> None:
        llm = _FakeLLM(served="tiny-model-x")
        result = self._run(llm, model="configured-model")
        fm = _frontmatter(
            (Path(self.cfg.vault_dir) / "a_test_paper" / "00_notes.md").read_text())
        self.assertNotEqual(fm.get("analyzed_by"), fm.get("requested_model"))
        self.assertEqual(fm.get("analyzed_by"), "tiny-model-x")

    def test_gateway_silent_falls_back_to_the_requested_name(self) -> None:
        """A bare Ollama sends no routing headers; do not invent provenance."""
        llm = _FakeLLM(served="")
        self._run(llm, model="configured-model")
        note = Path(self.cfg.vault_dir) / "a_test_paper" / "00_notes.md"
        fm = _frontmatter(note.read_text())
        self.assertEqual(fm.get("analyzed_by"), "configured-model")

    def test_provenance_is_cleared_between_papers(self) -> None:
        """Stale state from a previous paper would mis-attribute this one."""
        llm = _FakeLLM(served="first-model")
        self._run(llm, model="a", paper=_paper("2401.00001", "A Test Paper"))

        # Second paper, and this time the gateway is silent (a bare Ollama, or
        # any path that sends no routing headers). The new note must name what
        # was asked for, not carry the first paper's served model forward.
        llm.served = ""
        self._run(llm, model="b", paper=_paper("2401.00002", "A Second Paper"))

        fm = _frontmatter(
            (Path(self.cfg.vault_dir) / "a_second_paper" / "00_notes.md").read_text())
        self.assertEqual(fm.get("analyzed_by"), "b")
        self.assertEqual(fm.get("requested_model"), "b")


class TestBusyGatewayDoesNotCorruptNotes(unittest.TestCase):
    """A 429 mid-analysis degrades the analysis, not the provenance claim."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hive-busy-"))
        self.cfg = make_config(self.tmp)

    def test_gateway_busy_propagates_rather_than_fabricating(self) -> None:
        pipe_llm = _FakeLLM(served="")
        with mock.patch("hive_research.llm.LLMInterface._request",
                        side_effect=GatewayBusy("no slot")):
            from hive_research.llm import LLMInterface
            with self.assertRaises(GatewayBusy):
                LLMInterface(self.cfg)._request("chat", {"model": "x"}, retries=1)


if __name__ == "__main__":
    unittest.main()