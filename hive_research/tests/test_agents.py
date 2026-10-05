"""Extraction agents: grounding, graceful gaps, and single verifier lifecycle.

These tests drive the swarm with a scripted offline model. They are the only
place the whole agent path -- contract check, call, event write, merge, verify --
runs without a gateway, so they are where a broken lifecycle shows up first.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest

from hive_research import agents as ag
from hive_research import ledger as lg
from hive_research import assurance_ledger as al
from hive_research.agents import Agent, NOT_PRODUCED
from hive_research.ledger_models import reset_store
from hive_research.tests.base import make_config


class ScriptedLLM:
    """Returns a role-appropriate superset, and can be told to fail a role."""

    def __init__(self, fail_on: str = "") -> None:
        self.fail_on = fail_on
        self.last_served_model = ""
        self.calls: list[str | None] = []

    def extract_structured(self, prompt: str, model=None, gpu_id=None,
                           system=None):
        self.calls.append(model)
        if "JSON list" in prompt:
            return {"tags": ["alignment", "agents"]}
        if self.fail_on and self.fail_on in prompt:
            raise RuntimeError("gateway exploded")
        if "verdict" in prompt.lower():
            return {"verdicts": [{"claim": "95.2", "verdict": "supported",
                                  "note": "in table 1"}]}
        return {
            "summary": "We reach 95.2 accuracy.",
            "tldr": "95.2 accuracy.",
            "notes": "The method reports 95.2 accuracy on the benchmark.",
            "limitations": "Small scale.",
            "experiments": [{"name": "e1", "results": "95.2"}],
            "experiment": {"methodology": "m"},
            "results": {"main_findings": "95.2"},
            "reproduction": {"datasets": ["d"]},
            "experiment_ideas": ["try larger"],
            "concepts": [{"name": "Attention", "definition": "d",
                          "relation": "uses"}],
            "relations": [],
            "lineage_notes": "Builds on prior work.",
        }


class AgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="hive-agents-")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(reset_store)
        reset_store()
        self.cfg = make_config(self.tmp.name)
        self.store = lg.init_store(self.cfg.ledger_db_path)
        al.record_run_start("run", actor="orchestrator", paper_id="2401.1",
                           store=self.store)
        self.text = ("Abstract. We present a method. "
                     + "Method details with 95.2 accuracy. " * 40)

    def _run(self, llm: ScriptedLLM) -> dict:
        return ag.run_extraction_swarm(
            run_id="run", title="Test Paper", text=self.text, llm=llm,
            config=self.cfg, graph_context="prior work", store=self.store)


class TestExtractionSwarm(AgentTestCase):
    def test_every_role_runs_and_merges(self) -> None:
        out = self._run(ScriptedLLM())
        roles = {r["role"]: r["ok"] for r in out["assurance"]["roles"]}
        self.assertEqual(set(roles), {a.role for a in ag.EXTRACTION_AGENTS})
        self.assertTrue(all(roles.values()), roles)
        self.assertEqual(out["tags"], ["alignment", "agents"])
        self.assertTrue(out["notes"])
        self.assertTrue(out["concepts"])

    def test_missing_role_output_becomes_an_explicit_marker(self) -> None:
        # The lineage role is the only producer of lineage_notes; make the model
        # return a dict without it so the merge must declare the gap.
        class NoLineage(ScriptedLLM):
            def extract_structured(self, prompt, model=None, gpu_id=None,
                                   system=None):
                data = super().extract_structured(prompt, model, gpu_id, system)
                if "lineage_notes" in prompt and "JSON list" not in prompt \
                        and "verdict" not in prompt.lower():
                    data.pop("lineage_notes", None)
                return data

        out = self._run(NoLineage())
        self.assertEqual(out["lineage_notes"], NOT_PRODUCED)

    def test_failed_role_does_not_take_down_the_swarm(self) -> None:
        llm = ScriptedLLM(fail_on="concepts")
        out = self._run(llm)
        self.assertIn("concept-extractor", out["assurance"]["roles_failed"])
        # The other roles still produced their half of the note.
        self.assertTrue(out["notes"])
        self.assertEqual(out["concepts"], NOT_PRODUCED)

    def test_run_is_not_allowed_when_a_role_failed(self) -> None:
        out = self._run(ScriptedLLM(fail_on="concepts"))
        self.assertFalse(out["assurance"]["policy"]["allowed"])
        self.assertIn("role_coverage",
                      out["assurance"]["policy"]["blocked_by"])

    def test_swarm_survives_without_a_ledger(self) -> None:
        """Ledgering off must degrade the audit, not the analysis."""
        reset_store()
        out = ag.run_extraction_swarm(
            run_id="run", title="Test Paper", text=self.text,
            llm=ScriptedLLM(), config=self.cfg, store=None)
        self.assertTrue(out["notes"])
        self.assertTrue(out["assurance"]["claims"])


class TestGrounding(AgentTestCase):
    def test_number_present_in_source_is_grounded(self) -> None:
        out = self._run(ScriptedLLM())
        grounding = out["assurance"]["grounding"]
        self.assertEqual(grounding["grounded_ratio"], 1.0)
        self.assertEqual(grounding["ungrounded"], [])

    def test_number_absent_from_source_is_ungrounded(self) -> None:
        class HallucinatingLLM(ScriptedLLM):
            def extract_structured(self, prompt, model=None, gpu_id=None,
                                   system=None):
                data = super().extract_structured(prompt, model, gpu_id, system)
                if "JSON list" not in prompt and "verdict" not in prompt.lower():
                    data["summary"] = "We reach 99.9 accuracy."
                return data

        out = self._run(HallucinatingLLM())
        self.assertIn("99.9", out["assurance"]["grounding"]["ungrounded"])
        claims = {c["claim"]: c for c in out["assurance"]["claims"]}
        self.assertFalse(claims["99.9"]["grounded"])


class TestVerifierLifecycle(AgentTestCase):
    def _events(self) -> list[dict]:
        return lg.run_events("run", store=self.store)

    def test_verifier_spawns_and_completes_exactly_once(self) -> None:
        self._run(ScriptedLLM())
        events = self._events()
        spawns = [e for e in events if e["kind"] == "swarm.spawn"
                  and (e["data"] or {}).get("role") == "verifier"]
        completes = [e for e in events if e["kind"] == "swarm.complete"
                     and (e["data"] or {}).get("role") == "verifier"]
        self.assertEqual(len(spawns), 1)
        self.assertEqual(len(completes), 1)

    def test_each_value_has_an_emit_and_a_verify_event(self) -> None:
        self._run(ScriptedLLM())
        kinds = [e["kind"] for e in self._events()]
        self.assertIn("claim.emit", kinds)
        self.assertIn("claim.verify", kinds)
        self.assertEqual(kinds.count("claim.emit"), kinds.count("claim.verify"))

    def test_chain_verifies_after_a_full_swarm(self) -> None:
        self._run(ScriptedLLM())
        report = lg.verify_chain("run", store=self.store)
        self.assertTrue(report["ok"], report["findings"])


class TestContextSelection(unittest.TestCase):
    def _agent(self, **kwargs) -> Agent:
        base = dict(role="r", intent="i", system="s",
                    build_prompt=lambda ctx: "", fields=("x",))
        base.update(kwargs)
        return Agent(**base)

    def test_short_text_is_returned_whole(self) -> None:
        agent = self._agent(max_chars=1000)
        self.assertEqual(ag._context_for(agent, "short paper"), "short paper")

    def test_long_text_is_bounded_by_max_chars(self) -> None:
        agent = self._agent(max_chars=100)
        out = ag._context_for(agent, "x" * 5000)
        self.assertLessEqual(len(out), 100)

    def test_method_weighting_prefers_the_method_section(self) -> None:
        text = ("## Abstract\n" + "abstract filler. " * 60
                + "\n\n## Method\n" + "METHODCONTENT " * 60
                + "\n\n## Conclusion\n" + "conclusion filler. " * 60)
        agent = self._agent(max_chars=300, system_context="method")
        out = ag._context_for(agent, text)
        self.assertIn("METHODCONTENT", out)


class TestThreadLocalProvenance(unittest.TestCase):
    def test_served_model_does_not_leak_between_paper_threads(self) -> None:
        """Parallel papers share one LLMInterface; provenance must not cross over."""
        from hive_research.llm import LLMInterface

        with tempfile.TemporaryDirectory() as tmp:
            llm = LLMInterface(make_config(tmp))

        barrier = threading.Barrier(2)
        seen: dict[str, str] = {}

        def worker(name: str) -> None:
            llm.last_served_model = name
            barrier.wait()          # both threads have set their value...
            time.sleep(0.05)        # ...before either reads it back
            seen[name] = llm.last_served_model

        threads = [threading.Thread(target=worker, args=(f"model-{i}",))
                   for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(seen, {"model-0": "model-0", "model-1": "model-1"})


if __name__ == "__main__":
    unittest.main()
