from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from hive_companion.hive_client import HiveClient
from hive_companion.ideagent import IdeagentEngine
from hive_companion.llm import ChatClient, LLMError

AnyResponse = httpx.Response | Exception


def _mock(routes: dict[tuple[str, str], list[AnyResponse]]):
    """routes maps (method, path) to responses popped per call."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        queue = routes.get((request.method, request.url.path), [])
        if not queue:
            return httpx.Response(404, text="no route")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler), calls


class TestPoolTopicPayload(unittest.TestCase):
    """hive expects {name, query} on add and {name} on remove — regression test."""

    def test_add_sends_name_and_query(self) -> None:
        transport, calls = _mock(
            {("POST", "/api/pool/topics/add"): [httpx.Response(200, json={"status": "ok"})]}
        )
        client = HiveClient("http://hive.test", transport=transport)
        asyncio.run(client.pool_topic_add("Agent security"))
        body = json.loads(calls[-1].content)
        self.assertEqual(body, {"name": "Agent security", "query": "Agent security"})

    def test_remove_sends_name(self) -> None:
        transport, calls = _mock(
            {("POST", "/api/pool/topics/remove"): [httpx.Response(200, json={"status": "ok"})]}
        )
        client = HiveClient("http://hive.test", transport=transport)
        asyncio.run(client.pool_topic_remove("Agent security"))
        body = json.loads(calls[-1].content)
        self.assertEqual(body, {"name": "Agent security"})


class TestChatClientRetry(unittest.TestCase):
    def _chat(self, responses: list[AnyResponse]) -> tuple[str | LLMError, int]:
        transport, calls = _mock({("POST", "/api/chat"): list(responses)})
        client = ChatClient("http://llm.test", "test-model", transport=transport)

        async def go() -> str:
            return await client.chat("sys", "user")

        try:
            result: str | LLMError = asyncio.run(go())
        except LLMError as exc:
            result = exc
        return result, len(calls)

    def test_empty_then_success_retries_with_larger_budget(self) -> None:
        empty = {"message": {"role": "assistant", "content": ""}, "done_reason": "length"}
        full = {"message": {"role": "assistant", "content": "{\"title\": \"x\"}"}, "done_reason": "stop"}
        result, calls = self._chat([httpx.Response(200, json=empty), httpx.Response(200, json=full)])
        self.assertEqual(result, "{\"title\": \"x\"}")
        self.assertEqual(calls, 2)

    def test_empty_stop_raises_with_reason(self) -> None:
        empty = {"message": {"role": "assistant", "content": ""}, "done_reason": "unload"}
        result, calls = self._chat([httpx.Response(200, json=empty)])
        self.assertIsInstance(result, LLMError)
        assert isinstance(result, LLMError)
        self.assertIn("unload", str(result))
        self.assertEqual(calls, 1)  # only 'length' triggers a retry

    def test_think_flag_fallback(self) -> None:
        ok = {"message": {"role": "assistant", "content": "hello"}}
        transport, calls = _mock(
            {
                ("POST", "/api/chat"): [
                    httpx.Response(400, text="model does not support think"),
                    httpx.Response(200, json=ok),
                ]
            }
        )
        client = ChatClient("http://llm.test", "old-model", transport=transport)

        async def go() -> str:
            return await client.chat("sys", "user")

        result = asyncio.run(go())
        self.assertEqual(result, "hello")
        first_body = json.loads(calls[0].content)
        second_body = json.loads(calls[1].content)
        self.assertIn("think", first_body)
        self.assertNotIn("think", second_body)


class _FakeLLM:
    def __init__(self, fail: bool = True) -> None:
        self.fail = fail

    async def chat(self, *args: object, **kwargs: object) -> str:
        if self.fail:
            raise LLMError("empty completion")
        return "{}"


class TestIdeagentLoudFailure(unittest.TestCase):
    def _engine(self, llm: _FakeLLM) -> IdeagentEngine:
        return IdeagentEngine(llm_fast=llm, llm_main=None, kg=object())  # type: ignore[arg-type]

    def test_all_failures_mark_run_failed(self) -> None:
        engine = self._engine(_FakeLLM(fail=True))

        async def go() -> None:
            await engine.run("topic x", iterations=3, wait=True)

        asyncio.run(go())
        run = engine.history[-1]
        self.assertEqual(run.status, "failed")
        assert run.error
        self.assertIn("all 3 iterations failed", run.error)

    def test_successful_run_reports_zero_failed_iterations(self) -> None:
        engine = self._engine(_FakeLLM(fail=False))

        async def go() -> None:
            await engine.run("topic y", iterations=2, wait=True)

        asyncio.run(go())
        data = engine.history[-1].to_dict()
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["failed_iterations"], 0)


if __name__ == "__main__":
    unittest.main()
