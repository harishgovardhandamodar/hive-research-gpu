"""Minimal async chat-completion client (Ollama-style /api/chat)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout)

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
            resp = await self._client.post(f"{self._base}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"llm unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"llm error {resp.status_code}: {resp.text[:200]}")
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
