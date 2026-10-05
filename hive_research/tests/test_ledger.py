"""The tamper-evident ledger: chain integrity, mandates, claims and redaction.

These tests are adversarial on purpose. A ledger that only proves itself correct
on a clean run has not been tested, because the whole point is what happens when
something is changed underneath it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hive_research import ledger as lg
from hive_research.ledger_models import init_store, reset_store


class LedgerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="hive-ledger-")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(reset_store)
        reset_store()
        self.store = init_store(Path(self.tmp.name) / "ledger.sqlite3")

    def _events(self, run_id: str) -> list[dict]:
        return lg.run_events(run_id, store=self.store)


class TestChainIntegrity(LedgerTestCase):
    def test_append_and_verify_round_trip(self) -> None:
        lg.append("r1", "run.start", "orchestrator", store=self.store)
        lg.append("r1", "swarm.spawn", "orchestrator",
                  data={"role": "verifier"}, store=self.store)
        lg.append("r1", "run.end", "orchestrator", store=self.store)

        report = lg.verify_chain("r1", store=self.store)
        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["events"], 3)

    def test_first_event_links_to_genesis(self) -> None:
        lg.append("r1", "run.start", "orchestrator", store=self.store)
        first = self._events("r1")[0]
        self.assertEqual(first["prev_hash"], lg.GENESIS)

    def test_edited_event_is_detected(self) -> None:
        lg.append("r1", "run.start", "orchestrator", store=self.store)
        lg.append("r1", "llm.call", "tagger", data={"model_served": "a"},
                  store=self.store)
        lg.append("r1", "run.end", "orchestrator", store=self.store)

        # Change the middle event's payload without recomputing the chain, the
        # way anyone editing the database directly would.
        ev = self._events("r1")[1]
        data = dict(ev["data"])
        data["model_served"] = "b"
        self.store.conn.execute(
            "UPDATE ledger_events SET data_json = ? WHERE run_id = ? AND seq = ?",
            (lg.canon(data), "r1", ev["seq"]),
        )
        self.store.conn.commit()

        report = lg.verify_chain("r1", store=self.store)
        self.assertFalse(report["ok"])
        self.assertIn("content_tampered",
                      {f["issue"] for f in report["findings"]})

    def test_deleted_event_breaks_the_chain(self) -> None:
        for i in range(4):
            lg.append("r1", "tool.call", "t", intent=f"step{i}",
                      checked=False, store=self.store)
        self.store.conn.execute(
            "DELETE FROM ledger_events WHERE run_id = ? AND seq = 1", ("r1",))
        self.store.conn.commit()

        report = lg.verify_chain("r1", store=self.store)
        self.assertFalse(report["ok"])
        issues = {f["issue"] for f in report["findings"]}
        self.assertTrue({"sequence_gap", "broken_link"} & issues, issues)

    def test_reordering_is_visible_as_a_sequence_gap(self) -> None:
        for i in range(3):
            lg.append("r1", "tool.call", "t", intent=f"step{i}",
                      checked=False, store=self.store)
        # Swap the two recorded seq numbers to simulate a re-ordered log.
        self.store.conn.execute(
            "UPDATE ledger_events SET seq = 99 WHERE run_id = ? AND seq = 2",
            ("r1",))
        self.store.conn.commit()
        report = lg.verify_chain("r1", store=self.store)
        self.assertFalse(report["ok"])

    def test_unknown_run_fails_closed(self) -> None:
        report = lg.verify_chain("nope", store=self.store)
        self.assertFalse(report["ok"])
        self.assertEqual(report["findings"][0]["issue"], "unknown_run")


class TestMandate(LedgerTestCase):
    def test_run_end_over_budget_is_denied(self) -> None:
        mandate = lg.Mandate(objective="test", max_events=2)
        lg.ensure_run("r1", mandate=mandate, store=self.store)
        for i in range(4):
            lg.append("r1", "tool.call", "t", intent=f"s{i}", checked=False,
                      store=self.store)
        lg.append("r1", "run.end", "orchestrator", mandate=mandate,
                  store=self.store)
        end = self._events("r1")[-1]
        self.assertEqual(end["kind"], "run.end")
        self.assertEqual(end["verdict"], "deny")

    def test_internal_kinds_are_never_gated(self) -> None:
        """The trail must not be able to refuse to record that it was asked."""
        mandate = lg.Mandate(objective="test", allowed_intents=["only_this"],
                             max_events=1)
        lg.ensure_run("r1", mandate=mandate, store=self.store)
        # claim.emit is internal; even under a hostile mandate it is recorded.
        lg.append("r1", "claim.emit", "verifier", intent="not_allowed",
                  store=self.store)
        self.assertEqual(self._events("r1")[-1]["kind"], "claim.emit")

    def test_out_of_domain_source_is_flagged_not_denied(self) -> None:
        mandate = lg.Mandate(objective="test", allowed_domains=["arxiv.org"])
        lg.ensure_run("r1", mandate=mandate, store=self.store)
        lg.append("r1", "tool.call", "fetcher", data={"source": "evil.example"},
                  store=self.store)
        ev = self._events("r1")[-1]
        self.assertEqual(ev["verdict"], "flag")


class TestClaims(LedgerTestCase):
    def test_emit_and_verify_are_both_on_the_chain(self) -> None:
        lg.append("r1", "run.start", "orchestrator", store=self.store)
        emitted = lg.emit_claim("r1", "95.2", actor="verifier",
                                verdict="unsupported", verifier="substring",
                                store=self.store)
        lg.verify_claim("r1", emitted["claim_hash"], "supported",
                        verifier="substring+model", store=self.store)

        kinds = [e["kind"] for e in self._events("r1")]
        self.assertIn("claim.emit", kinds)
        self.assertIn("claim.verify", kinds)
        claims = lg.run_claims("r1", store=self.store)
        self.assertEqual(claims[0]["verdict"], "supported")

    def test_claim_text_tamper_is_detected(self) -> None:
        lg.append("r1", "run.start", "orchestrator", store=self.store)
        lg.emit_claim("r1", "95.2", actor="verifier", store=self.store)
        self.store.conn.execute(
            "UPDATE ledger_claims SET text = ? WHERE run_id = ?", ("12.5", "r1"))
        self.store.conn.commit()
        report = lg.verify_chain("r1", store=self.store)
        self.assertFalse(report["ok"])
        self.assertIn("claim_tampered", {f["issue"] for f in report["findings"]})

    def test_event_refs_are_resolved_against_the_bundle(self) -> None:
        lg.append("r1", "run.start", "orchestrator", store=self.store)
        lg.append("r1", "tool.call", "t", input_refs=["f" * 64, "a" * 64],
                  checked=False, store=self.store)
        report = lg.verify_chain("r1", store=self.store)
        self.assertFalse(report["ok"])
        self.assertIn("unresolved_input_ref",
                      {f["issue"] for f in report["findings"]})


class TestRedaction(LedgerTestCase):
    def test_secrets_are_redacted_by_default(self) -> None:
        lg.append("r1", "llm.call", "t", data={"api_key": "sk-super-secret"},
                  checked=False, store=self.store)
        raw = self.store.conn.execute(
            "SELECT data_json FROM ledger_events WHERE run_id = ?", ("r1",)
        ).fetchone()["data_json"]
        self.assertNotIn("sk-super-secret", raw)
        self.assertIn("redacted", raw)

    def test_prompt_text_is_hashed_not_stored(self) -> None:
        from hive_research import assurance_ledger as al

        lg.append("r1", "run.start", "o", store=self.store)
        out = al.record_prompt_fingerprint(
            "r1", actor="tagger", model="m",
            prompt="the whole paper goes here", store=self.store)
        self.assertTrue(out["prompt_hash"])
        raw = self.store.conn.execute(
            "SELECT data_json FROM ledger_events WHERE run_id = ? AND kind = 'model.prompt'",
            ("r1",)
        ).fetchone()["data_json"]
        self.assertNotIn("the whole paper goes here", raw)
        self.assertIn(out["prompt_hash"], raw)


class TestStoreIsolation(unittest.TestCase):
    def test_reset_store_drops_the_previous_database(self) -> None:
        """Two temp dirs must not share a store, or tests poison each other."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            reset_store()
            try:
                s1 = init_store(Path(a) / "l.sqlite3")
                lg.append("r1", "run.start", "o", store=s1)
                reset_store()
                s2 = init_store(Path(b) / "l.sqlite3")
                self.assertNotEqual(s2.db_path, s1.db_path)
                # The run written to A must not exist in B's database.
                self.assertIsNone(lg.get_run("r1", store=s2))
            finally:
                reset_store()


if __name__ == "__main__":
    unittest.main()
