"""The fox-services gateway boundary: attribution, provenance, and backpressure.

Three failures this pins, all observed against a live gateway:

1. No ``X-Service-Name`` on the request means the gateway files every call as
   ``gateway-unknown`` -- this app was the third-largest caller in the
   telemetry table and was not identifiable in it.
2. The gateway substitutes models (it prefers one already loaded over paying a
   cold load). A client that ignores ``X-Served-Model`` writes notes claiming
   a 27B model wrote them when a 3B model did.
3. The gateway holds a request for its own 600s slot wait before forwarding.
   A client that gives up first reports a dead gateway rather than a busy one,
   and a 429 needs to be distinguishable from a transport error.

No network: ``requests.post`` is patched.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import requests

from hive_research.llm import GatewayBusy, LLMInterface
from hive_research.server import _served_by
from hive_research.tests.base import TempDirTestCase, make_config


class FakeResponse:
    """Minimal stand-in for requests.Response, headers included."""

    def __init__(
        self,
        payload: dict,
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _chat_response(model: str, **headers: str) -> FakeResponse:
    return FakeResponse(
        {"model": model, "message": {"role": "assistant", "content": "ok"}},
        headers=headers,
    )


def _embed_response(model: str = "nomic-embed-text:latest",
                    **headers: str) -> FakeResponse:
    return FakeResponse(
        {"model": model, "embeddings": [[0.1, 0.2, 0.3]]},
        headers=headers,
    )


class TestAttribution(TempDirTestCase):
    """Without these headers the gateway cannot tell who is calling."""

    def test_request_carries_service_name_and_requestor(self) -> None:
        cfg = make_config(self.tmp)
        captured: dict = {}

        def _capture(url, **kwargs):
            captured.update(kwargs)
            captured["url"] = url
            return _chat_response("test-large")

        with mock.patch("hive_research.llm.requests.post", _capture):
            LLMInterface(cfg).generate("hi")

        headers = captured.get("headers") or {}
        self.assertEqual(headers.get("X-Service-Name"), "hive-research-gpu")
        self.assertEqual(headers.get("X-Requestor"), "subagent")

    def test_service_name_is_configurable(self) -> None:
        cfg = make_config(self.tmp)
        cfg.data.setdefault("ollama", {})["service_name"] = "custom-name"
        captured: dict = {}

        def _capture(url, **kwargs):
            captured.update(kwargs)
            return _chat_response("test-large")

        with mock.patch("hive_research.llm.requests.post", _capture):
            LLMInterface(cfg).generate("hi")

        self.assertEqual((captured.get("headers") or {}).get("X-Service-Name"),
                         "custom-name")


class TestServedModelProvenance(TempDirTestCase):
    """The gateway may answer with a different model than the one requested."""

    def test_substitution_is_recorded_not_silently_accepted(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)

        resp = _chat_response(
            "some-other-model",
            **{"X-Served-Model": "some-other-model",
               "X-Original-Model": "test-large",
               "X-Served-Node": "peer-node-1",
               "X-Routing-Reason": "rewritten to already loaded preferred"},
        )
        with mock.patch("hive_research.llm.requests.post", return_value=resp):
            llm.generate("hi")

        # The served name is remembered, and it is the *served* name.
        self.assertEqual(llm.last_served_model, "some-other-model")
        self.assertEqual(llm.last_served_node, "peer-node-1")

    def test_substitution_is_kept_on_the_client_for_the_note_writer(self) -> None:
        """The pipeline reads this attribute when it stamps provenance."""
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        resp = _chat_response("served-model-x",
                              **{"X-Served-Model": "served-model-x"})
        with mock.patch("hive_research.llm.requests.post", return_value=resp):
            llm.generate("hi")
        self.assertEqual(llm.last_served_model, "served-model-x")

    def test_matching_model_still_recorded(self) -> None:
        """'We asked for X and got X' is only knowable by looking."""
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        resp = _chat_response("test-large",
                              **{"X-Served-Model": "test-large"})
        with mock.patch("hive_research.llm.requests.post", return_value=resp):
            llm.generate("hi")
        self.assertEqual(llm.last_served_model, "test-large")

    def test_no_gateway_headers_leaves_previous_value_untouched(self) -> None:
        """A bare Ollama sends no routing headers; do not invent a model."""
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        with mock.patch("hive_research.llm.requests.post",
                        return_value=_chat_response("test-large")):
            llm.generate("hi")
        self.assertEqual(llm.last_served_model, "")

    def test_optional_tag_is_not_reported_as_a_substitution(self) -> None:
        """"nomic-embed-text" and "...:latest" are one model, not two.

        Embeds run per chunk per ingest, so treating the tag difference as a
        substitution warns on every call and teaches the operator to ignore
        warnings.
        """
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        resp = _embed_response(**{
            "X-Served-Model": "nomic-embed-text:latest",
            "X-Routing-Reason": "rewritten to loaded same-size nomic-embed-text:latest"})
        with mock.patch("hive_research.llm.requests.post", return_value=resp):
            with self.assertNoLogs("hive_research.llm", level="WARNING"):
                vector = llm.embed("some text", model="nomic-embed-text")

        # Still remembered for provenance -- just not shouted about.
        self.assertEqual(llm.last_served_model, "nomic-embed-text:latest")
        self.assertEqual(len(vector), 3)

    def test_genuinely_different_model_still_warns(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        resp = _embed_response(**{
            "X-Served-Model": "llama3.2:3b",
            "X-Routing-Reason": "rewritten to loaded same-kind llama3.2:3b"})
        with mock.patch("hive_research.llm.requests.post", return_value=resp):
            with self.assertLogs("hive_research.llm", level="WARNING") as logs:
                vector = llm.embed("some text")

        self.assertIn("llama3.2:3b", "\n".join(logs.output))
        self.assertEqual(len(vector), 3)


class TestBackpressure(TempDirTestCase):
    """The gateway can hold a request for 600s. The client must wait longer."""

    def test_chat_uses_configured_timeout_not_a_hardcoded_short_one(self) -> None:
        cfg = make_config(self.tmp)
        seen: dict = {}

        def _capture(url, **kwargs):
            seen.update(kwargs)
            return _chat_response("test-large")

        with mock.patch("hive_research.llm.requests.post", _capture):
            LLMInterface(cfg).chat([{"role": "user", "content": "hi"}])

        # The gateway's slot wait alone is 600s; anything under that gives up
        # while the slot is still held.
        self.assertGreaterEqual(seen.get("timeout") or 0, cfg.ollama_timeout)

    def test_429_raises_gateway_busy_instead_of_a_generic_error(self) -> None:
        cfg = make_config(self.tmp)
        busy = FakeResponse({"error": "gateway busy: no slot"}, status_code=429)
        with mock.patch("hive_research.llm.requests.post", return_value=busy):
            with self.assertRaises(GatewayBusy):
                LLMInterface(cfg)._request("chat", {"model": "test-large"},
                                           retries=1)

    def test_chat_degrades_to_empty_string_on_429(self) -> None:
        """chat() is a best-effort helper; it returns "" rather than raising."""
        cfg = make_config(self.tmp)
        busy = FakeResponse({"error": "gateway busy: no slot"}, status_code=429)
        with mock.patch("hive_research.llm.requests.post", return_value=busy):
            out = LLMInterface(cfg).chat([{"role": "user", "content": "hi"}])
        self.assertEqual(out, "")

    def test_429_is_not_retried_three_times(self) -> None:
        """Retrying re-enters the same queue; the honest answer is to give up."""
        cfg = make_config(self.tmp)
        busy = FakeResponse({"error": "gateway busy"}, status_code=429)
        calls: list = []

        def _count(url, **kwargs):
            calls.append(url)
            return busy

        with mock.patch("hive_research.llm.requests.post", _count), \
                mock.patch("hive_research.llm.time.sleep"):
            with self.assertRaises(GatewayBusy):
                LLMInterface(cfg)._request("chat", {"model": "test-large"},
                                           retries=3)
        self.assertEqual(len(calls), 1)


class TestEmbedRouting(TempDirTestCase):
    """Embeddings go through the gateway too, so they are accounted for."""

    def test_embed_uses_same_base_when_no_override(self) -> None:
        cfg = make_config(self.tmp)
        seen: dict = {}

        def _capture(url, **kwargs):
            seen["url"] = url
            return FakeResponse({"embeddings": [[0.1, 0.2]]})

        with mock.patch("hive_research.llm.requests.post", _capture):
            vec = LLMInterface(cfg).embed("text")

        self.assertEqual(seen["url"], "http://localhost:11434/api/embed")
        self.assertEqual(vec, [0.1, 0.2])

    def test_embed_carries_attribution_too(self) -> None:
        cfg = make_config(self.tmp)
        seen: dict = {}

        def _capture(url, **kwargs):
            seen.update(kwargs)
            return FakeResponse({"embeddings": [[0.1]]})

        with mock.patch("hive_research.llm.requests.post", _capture):
            LLMInterface(cfg).embed("text")

        self.assertEqual((seen.get("headers") or {}).get("X-Service-Name"),
                         "hive-research-gpu")

    def test_a_gpu_id_does_not_route_around_the_gateway(self) -> None:
        """A scheduling hint must not cost attribution and provenance.

        ``embed_parallel`` hands every chunk a gpu_id. If that overrode the
        base URL, every embed in a large ingest would leave the gateway:
        unattributed in telemetry, no X-Served-Model, managed pool skipped.
        """
        cfg = make_config(self.tmp)
        seen: dict = {}

        def _capture(url, **kwargs):
            seen["url"] = url
            return FakeResponse({"embeddings": [[0.1, 0.2]]})

        gpu_mgr = mock.Mock()
        gpu_mgr.device_count.return_value = 2
        gpu_mgr.get_ollama_url.return_value = "http://localhost:11435"

        with mock.patch("hive_research.llm.requests.post", _capture):
            LLMInterface(cfg, gpu_mgr).embed("text", gpu_id=1)

        self.assertEqual(seen["url"], "http://localhost:11434/api/embed")
        gpu_mgr.get_ollama_url.assert_not_called()

    def test_direct_gpu_routing_is_available_but_opt_in(self) -> None:
        """For a box deliberately running one Ollama per GPU."""
        cfg = make_config(self.tmp)
        seen: dict = {}

        def _capture(url, **kwargs):
            seen["url"] = url
            return FakeResponse({"message": {"content": "ok"}})

        gpu_mgr = mock.Mock()
        gpu_mgr.device_count.return_value = 2
        gpu_mgr.get_ollama_url.return_value = "http://localhost:11435"

        with mock.patch.dict(os.environ, {"OLLAMA_DIRECT_GPU_ROUTING": "true"}):
            with mock.patch("hive_research.llm.requests.post", _capture):
                LLMInterface(cfg, gpu_mgr).generate("hi", gpu_id=1)

        self.assertEqual(seen["url"], "http://localhost:11435/api/chat")


class TestGatewayStatus(TempDirTestCase):
    """The About panel reports what the gateway can serve, not just /api/tags."""

    def test_router_status_is_preferred_and_parsed(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        status = {"gateway_enabled": True,
                  "slots": {"loaded_models": ["test-large"]},
                  "queues": {"pending": 2, "active": 1},
                  "policy": {"preferred": ["test-large"]}}
        tags = {"models": [{"name": "test-large"}]}

        def _route(url, **kwargs):
            if url.endswith("/api/router/status"):
                return FakeResponse(status)
            return FakeResponse(tags)

        with mock.patch("hive_research.llm.requests.get", _route):
            out = llm.gateway_status()

        self.assertTrue(out["reachable"])
        self.assertEqual(out["loaded_models"], ["test-large"])
        self.assertEqual(out["pending"], 2)
        self.assertEqual(out["service_name"], "hive-research-gpu")

    def test_falls_back_to_tags_when_router_status_unavailable(self) -> None:
        """A bare Ollama has no /api/router/status; the panel must still work."""
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)

        def _route(url, **kwargs):
            if url.endswith("/api/router/status"):
                return FakeResponse({"error": "nope"}, status_code=404)
            return FakeResponse({"models": [{"name": "test-large"}]})

        with mock.patch("hive_research.llm.requests.get", _route):
            out = llm.gateway_status()

        self.assertTrue(out["reachable"])
        self.assertIn("test-large", out.get("models") or [])

    def test_unreachable_gateway_is_reported_not_raised(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        with mock.patch("hive_research.llm.requests.get",
                        side_effect=requests.ConnectionError("down")):
            out = llm.gateway_status()
        self.assertFalse(out["reachable"])


class TestAvailabilityReporting(TempDirTestCase):
    """/api/ollama availability flags, as the About panel reads them."""

    def test_optional_tag_does_not_read_as_a_missing_model(self) -> None:
        """/api/tags lists "nomic-embed-text:latest"; we ask for "nomic-embed-text".

        An exact-match check reports a resident embedder as missing, so the
        panel contradicts the gateway's own loaded_models shown beside it.
        """
        installed = ["qwen3.8:27b", "nomic-embed-text:latest"]
        self.assertTrue(_served_by(installed, "nomic-embed-text"))
        self.assertTrue(_served_by(installed, "nomic-embed-text:latest"))
        self.assertTrue(_served_by(installed, "qwen3.8:27b"))

    def test_a_genuinely_absent_model_is_still_reported_missing(self) -> None:
        installed = ["qwen3.8:27b", "nomic-embed-text:latest"]
        self.assertFalse(_served_by(installed, "llama3.2:3b"))
        self.assertFalse(_served_by([], "qwen3.8:27b"))
        self.assertFalse(_served_by(installed, ""))

    def test_a_different_model_under_the_same_base_name_is_not_a_match(self) -> None:
        """Tag-insensitivity must not become prefix-insensitivity."""
        self.assertFalse(_served_by(["nomic-embed-text:large"], "nomic-embed-text"))


class TestVerifiability(TempDirTestCase):
    """A gateway that reports nothing must not be read as proof.

    Observed on an older axiom-1 fox-services: asked for qwen3.8:27b, got
    llama3.2:3b, and no X-Served-Model header. Filling in the requested model
    would make every note claim an author that never wrote it.
    """

    def test_missing_header_is_recorded_as_unverifiable(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        with mock.patch("hive_research.llm.requests.post",
                        return_value=_chat_response("test-large")):
            llm.generate("hi")

        self.assertFalse(llm.served_model_verifiable)
        # Not invented: the client refuses to name a model it did not see.
        self.assertEqual(llm.last_served_model, "")

    def test_it_warns_exactly_once(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        with mock.patch("hive_research.llm.requests.post",
                        return_value=_chat_response("test-large")):
            with self.assertLogs("hive_research.llm", level="WARNING") as logs:
                for _ in range(5):
                    llm.generate("hi")
                    llm.last_served_model = ""

        self.assertEqual(len(logs.output), 1)
        self.assertIn("no X-Served-Model", logs.output[0])

    def test_a_reporting_gateway_stays_verifiable(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        with mock.patch("hive_research.llm.requests.post",
                        return_value=_chat_response("served-x",
                                                    **{"X-Served-Model": "served-x"})):
            llm.generate("hi")

        self.assertTrue(llm.served_model_verifiable)

    def test_status_reports_verifiability_to_the_panel(self) -> None:
        cfg = make_config(self.tmp)
        llm = LLMInterface(cfg)
        with mock.patch("hive_research.llm.requests.post",
                        return_value=_chat_response("test-large")):
            llm.generate("hi")

        def _route(url, **kwargs):
            return FakeResponse({"gateway_enabled": True, "slots": {},
                                 "queues": {}, "policy": {}})

        with mock.patch("hive_research.llm.requests.get", _route):
            out = llm.gateway_status()
        self.assertFalse(out["served_model_verifiable"])


if __name__ == "__main__":
    unittest.main()