"""Swarm orchestration: contracts, policy gates, topology and typed hand-offs."""

from __future__ import annotations

import unittest

from hive_research import swarm as sw


class TestRoleContracts(unittest.TestCase):
    def test_every_swarm_role_has_a_contract(self) -> None:
        for roles in sw.SWARMS.values():
            for role in roles:
                self.assertIn(role, sw.ROLE_CONTRACTS, role)

    def test_unknown_role_is_not_contracted(self) -> None:
        result = sw.check_contract("definitely-not-a-role", {})
        self.assertFalse(result["contracted"])

    def test_missing_input_is_reported_not_guessed(self) -> None:
        required = sw.check_contract("verifier", {})["required"]
        self.assertTrue(required)
        payload = {k: "present" for k in required}
        self.assertTrue(sw.check_contract("verifier", payload)["ok"])
        del payload[required[0]]
        result = sw.check_contract("verifier", payload)
        self.assertIn(required[0], result["missing_inputs"])


class TestPolicyEnforcementPoint(unittest.TestCase):
    def _run(self, **kwargs):
        base = {"source_kind": "full_text", "grounded_ratio": 0.9,
                "required_roles": ["a", "b"], "roles_ran": ["a", "b"]}
        base.update(kwargs)
        return sw.policy_enforcement_point(**base)

    def test_healthy_run_is_allowed(self) -> None:
        result = self._run()
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "publish_allowed")

    def test_missing_role_blocks_publication(self) -> None:
        result = self._run(roles_ran=["a"])
        self.assertFalse(result["allowed"])
        self.assertIn("role_coverage", result["blocked_by"])

    def test_abstract_only_without_declaration_blocks(self) -> None:
        result = self._run(source_kind="abstract_only")
        self.assertFalse(result["allowed"])

    def test_low_grounding_warns_but_does_not_block(self) -> None:
        result = self._run(grounded_ratio=0.1)
        self.assertTrue(result["allowed"])
        self.assertIn("grounding_floor", result["warnings"])
        self.assertGreater(result["confidence_penalty"], 0)

    def test_zero_numbers_does_not_block_a_theory_paper(self) -> None:
        result = self._run(grounded_ratio=None)
        self.assertTrue(result["allowed"])
        computed = next(c for c in result["checks"]
                        if c["id"] == "grounding_computed")
        self.assertFalse(computed["passed"])
        self.assertEqual(computed["severity"], "info")

    def test_no_source_at_all_blocks(self) -> None:
        result = self._run(source_kind="none")
        self.assertFalse(result["allowed"])
        self.assertIn("source_adequacy", result["blocked_by"])


class TestPolicyEngine(unittest.TestCase):
    def test_denied_source_scope_blocks(self) -> None:
        result = sw.policy_engine(sources=["evil.example"],
                                  allowed_sources=["arxiv.org"])
        self.assertFalse(result["allowed"])
        self.assertIn("source_scope", result["blocked_by"])

    def test_budget_overrun_blocks(self) -> None:
        result = sw.policy_engine(budget_used={"llm_calls": 99},
                                  budget={"llm_calls": 3})
        self.assertFalse(result["allowed"])
        self.assertIn("ingest_budget", result["blocked_by"])


class TestScopeAndBudget(unittest.TestCase):
    def test_empty_allow_list_allows(self) -> None:
        self.assertTrue(sw.check_scope("fetch", "anywhere", [])["allowed"])

    def test_source_outside_allow_list_denies(self) -> None:
        self.assertFalse(
            sw.check_scope("fetch", "evil.example", ["arxiv.org"])["allowed"])

    def test_budget_allows_within_limits(self) -> None:
        result = sw.budget_allows({"llm_calls": 2}, {"llm_calls": 5})
        self.assertTrue(result["allowed"])

    def test_budget_reports_each_exceeded_limit(self) -> None:
        result = sw.budget_allows({"llm_calls": 6, "tool_calls": 1},
                                  {"llm_calls": 5, "tool_calls": 40})
        self.assertEqual(result["exceeded"], ["llm_calls"])


class TestHandoff(unittest.TestCase):
    def test_valid_handoff_passes_schema(self) -> None:
        ok = sw.validate_handoff({
            "run_id": "r", "parent_event": "a" * 64, "from_role": "a",
            "to_role": "b", "model_version": "m", "confidence": 0.8})
        self.assertTrue(ok["ok"])

    def test_missing_lineage_is_rejected(self) -> None:
        result = sw.validate_handoff({
            "run_id": "r", "from_role": "a", "to_role": "b",
            "model_version": "m", "confidence": 0.8})
        self.assertFalse(result["ok"])
        self.assertIn("parent_event", result["missing"])


class TestTopologyHealthResume(unittest.TestCase):
    def _events(self) -> list[dict]:
        def ev(seq, role, phase, kind=None):
            return {"seq": seq, "kind": kind or f"swarm.{phase}",
                    "actor": "orchestrator", "data": {"role": role,
                                                      "phase": phase}}
        return [
            {"seq": 0, "kind": "run.start", "actor": "orchestrator", "data": {}},
            ev(1, "tag-classifier", "spawn"),
            ev(2, "tag-classifier", "complete"),
            ev(3, "verifier", "spawn"),
            ev(4, "verifier", "failure", kind="swarm.failure"),
        ]

    def test_topology_separates_complete_from_failed(self) -> None:
        topo = sw.topology(self._events())
        self.assertIn("tag-classifier", topo["complete"])
        self.assertIn("verifier", topo["failed"])
        self.assertIn("source-collector", topo["pending"])

    def test_health_counts_failures(self) -> None:
        health = sw.health(self._events())
        verifier = next(r for r in health["roles"] if r["role"] == "verifier")
        self.assertEqual(verifier["failures"], 1)
        self.assertEqual(verifier["success_rate"], 0.0)

    def test_resume_reports_unfinished_roles(self) -> None:
        resume = sw.resume_state(self._events())
        self.assertTrue(resume["restartable"])
        # The verifier appears in the log, so the reconstructable phase is
        # "verified" even though that verifier then failed.
        self.assertEqual(resume["phase"], "verified")
        self.assertIn("tag-classifier", resume["completed"])
        self.assertIn("verifier", resume["completed"])
        # A role that finished and one that failed are both settled; neither is
        # something a restart should blindly re-run.
        self.assertNotIn("tag-classifier", resume["resume_these"])
        self.assertIn("source-collector", resume["pending"])

    def test_closed_run_is_not_restartable(self) -> None:
        events = self._events() + [
            {"seq": 5, "kind": "run.end", "actor": "orchestrator", "data": {}}]
        self.assertFalse(sw.resume_state(events)["restartable"])


class TestCritic(unittest.TestCase):
    def test_empty_section_is_a_finding(self) -> None:
        report = sw.critic_review([], analysis={"summary": "", "notes": "x"})
        ids = {f["id"] for f in report["findings"]}
        self.assertIn("EMPTY-SUMMARY", ids)
        self.assertFalse(report["clean"])

    def test_ungrounded_numbers_are_a_finding(self) -> None:
        report = sw.critic_review(
            [], analysis={"summary": "ok"},
            assurance={"grounding": {"ungrounded": ["99.9"]}})
        self.assertIn("UNGROUNDED-NUMBERS",
                      {f["id"] for f in report["findings"]})

    def test_clean_run_has_no_findings(self) -> None:
        report = sw.critic_review(
            [{"seq": 0, "kind": "run.start", "actor": "o", "data": {}}],
            analysis={"summary": "ok", "limitations": "none",
                      "lineage_notes": "prior"},
            assurance={"grounding": {"ungrounded": []},
                       "provenance": {"analyzed_by": "m"}})
        self.assertTrue(report["clean"])


if __name__ == "__main__":
    unittest.main()
