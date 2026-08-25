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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

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
            # Thinking models otherwise spend the whole num_predict budget on
            # message.thinking and return empty content (done_reason: length).
            "think": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if json_mode:
            body["format"] = "json"
        try:
            resp = await self._client.post(f"{self._base}/api/chat", json=body)
            if resp.status_code >= 400 and "think" in resp.text.lower():
                # model predates the think flag; retry without it
                body.pop("think")
                resp = await self._client.post(f"{self._base}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"llm unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"llm error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            # Generation may have been cut off before any answer text; give it
            # one more chance with a much larger budget before giving up.
            if data.get("done_reason") == "length":
                body["options"]["num_predict"] = num_predict * 4
                try:
                    resp = await self._client.post(f"{self._base}/api/chat", json=body)
                except httpx.HTTPError as exc:
                    raise LLMError(f"llm unreachable: {exc}") from exc
                data = resp.json()
                content = data.get("message", {}).get("content", "")
        if not content:
            reason = data.get("done_reason") or "no output"
            raise LLMError(f"empty completion (done_reason: {reason})")
        return content

    async def available(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base}/api/tags")
            return resp.status_code < 400
        except httpx.HTTPError:
            return False
