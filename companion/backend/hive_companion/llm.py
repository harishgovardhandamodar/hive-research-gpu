"""Minimal async chat-completion client (Ollama-style /api/chat)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        service_name: str = "hive-research-gpu-companion",
        requestor: str = "agent",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout)
        # Attribution headers. The gateway groups telemetry by X-Service-Name;
        # without it the companion's plans and ideation calls are filed as
        # gateway-unknown alongside ad-hoc curl.
        self._headers = {"X-Service-Name": service_name, "X-Requestor": requestor}
        self.last_served_model = ""

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
        num_predict: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if json_mode:
            body["format"] = "json"
        try:
            resp = await self._client.post(f"{self._base}/api/chat", json=body,
                                           headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"llm unreachable: {exc}") from exc
        if resp.status_code == 429:
            # The gateway's own slot wait ran out. Distinguish it: this is
            # contention, not a bad request, and the plan executor's retry
            # treats it as fatal rather than backoff-worthy.
            raise LLMError(f"gateway busy: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise LLMError(f"llm error {resp.status_code}: {resp.text[:200]}")
        # The gateway may serve a different model than requested (it prefers
        # one that is already loaded). Remember which one answered so the UI
        # can say so -- otherwise a plan looks like it came from the model the
        # operator configured when it did not.
        served = resp.headers.get("X-Served-Model") or ""
        if served:
            self.last_served_model = served
            # Tag-insensitive: an optional ":latest" is the same weights, not a
            # substitution, and warning on it trains the reader to ignore us.
            if served.split(":", 1)[0].strip().lower() != self._model.split(":", 1)[0].strip().lower():
                logger.warning(
                    "gateway served %s instead of %s (%s)",
                    served, self._model,
                    resp.headers.get("X-Routing-Reason") or "no reason given")
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise LLMError("empty completion")
        return content

    async def available(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base}/api/tags")
            return resp.status_code < 400
        except httpx.HTTPError:
            return False
