"""Async client for the main hive-research HTTP API.

The companion never touches the app's data files directly: every read and
mutation goes through the running server so there is exactly one writer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HiveApiError(RuntimeError):
    def __init__(self, path: str, status: int, body: str) -> None:
        super().__init__(f"GET {path} -> {status}: {body[:200]}")
        self.path = path
        self.status = status


class HiveClient:
    # Read-only POST endpoints — safe to retry on transport errors.
    _SAFE_POSTS = {"/api/query", "/api/search", "/api/similarity"}

    def __init__(self, base_url: str, token: str = "", timeout: float = 600.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _retryable(self, method: str, path: str) -> bool:
        return method == "GET" or path in self._SAFE_POSTS

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        headers = {"X-Hive-Token": self._token} if self._token else {}
        attempts = 2 if self._retryable(method, path) else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await self._client.request(
                    method, f"{self._base}{path}", json=json_body or {}, params=params or {}, headers=headers
                )
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("hive %s %s failed (attempt %d/%d): %s", method, path, attempt + 1, attempts, exc)
                if attempt + 1 < attempts:
                    await asyncio.sleep(2.0)
        else:
            raise HiveApiError(path, 0, f"connection failed: {last_exc}")
        if resp.status_code >= 400:
            raise HiveApiError(path, resp.status_code, resp.text)
        if not resp.content:
            return {}
        return resp.json()

    async def get(self, path: str, **params: str) -> Any:
        return await self._request("GET", path, params={k: v for k, v in params.items() if v})

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json_body=body)

    # -- reads ---------------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        return await self.get("/api/stats")

    async def papers(self, query: str = "", limit: int | None = None) -> list[dict[str, Any]]:
        data = await self.get("/api/papers", q=query, limit=str(limit) if limit else "")
        items = data.get("items", data) if isinstance(data, dict) else data
        return items or []

    async def paper_search(self, query: str) -> list[dict[str, Any]]:
        result = await self.post("/api/search", {"query": query})
        return result if isinstance(result, list) else result.get("items", [])

    async def rag_query(self, question: str) -> dict[str, Any]:
        return await self.post("/api/query", {"question": question})

    async def graph_clusters(self) -> Any:
        return await self.get("/api/graph/clusters")

    async def similarity(self, paper_ids: list[str], algorithm: str = "combined") -> Any:
        return await self.post("/api/similarity", {"paper_ids": paper_ids, "algorithm": algorithm})

    async def pool_papers(self) -> list[dict[str, Any]]:
        data = await self.get("/api/pool/papers")
        items = data.get("papers", data.get("items", data)) if isinstance(data, dict) else data
        return items or []

    async def pool_topics(self) -> Any:
        return await self.get("/api/pool/topics")

    async def feedback_summary(self) -> dict[str, Any]:
        return await self.get("/api/feedback")

    async def digest(self) -> dict[str, Any]:
        return await self.get("/api/digest")

    async def jobs(self) -> Any:
        return await self.get("/api/jobs")

    async def gpu(self) -> dict[str, Any]:
        return await self.get("/api/gpu")

    async def fox_modes(self) -> Any:
        return await self.get("/api/fox/modes")

    async def fox_conversations(self) -> list[dict[str, Any]]:
        data = await self.get("/api/fox/conversations")
        items = data.get("conversations", data) if isinstance(data, dict) else data
        return items or []

    async def fox_chat(
        self,
        message: str,
        mode: str = "rag",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"message": message, "mode": mode}
        if conversation_id:
            body["conversation_id"] = conversation_id
        return await self.post("/api/fox/chat", body)

    # -- mutations -----------------------------------------------------------

    async def add_paper(self, arxiv_id: str, model: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"id": arxiv_id}
        if model:
            body["model"] = model
        return await self.post("/api/add", body)

    async def import_query(self, query: str, model: str | None = None) -> Any:
        body: dict[str, Any] = {"query": query}
        if model:
            body["model"] = model
        return await self.post("/api/import", body)

    async def refresh_paper(self, paper_id: str, model: str | None = None) -> Any:
        body: dict[str, Any] = {"paper_id": paper_id}
        if model:
            body["model"] = model
        return await self.post("/api/papers/refresh", body)

    async def refresh_all(self, model: str | None = None) -> Any:
        body: dict[str, Any] = {}
        if model:
            body["model"] = model
        return await self.post("/api/refresh", body)

    async def rag_rebuild(self) -> Any:
        return await self.post("/api/rag/rebuild")

    async def improve_run(self) -> Any:
        return await self.post("/api/improve/run")

    async def fox_survey(self, topic: str) -> Any:
        return await self.post("/api/fox/survey", {"topic": topic})

    async def pool_import(self, topic: str, max_results: int | None = None) -> Any:
        body: dict[str, Any] = {"topic": topic}
        if max_results:
            body["max_results"] = max_results
        return await self.post("/api/pool/import", body)

    async def pool_topic_add(self, topic: str) -> Any:
        return await self.post("/api/pool/topics/add", {"topic": topic})

    async def pool_topic_remove(self, topic: str) -> Any:
        return await self.post("/api/pool/topics/remove", {"topic": topic})

    async def record_feedback(
        self,
        kind: str,
        rating: int,
        comment: str = "",
        **context: Any,
    ) -> Any:
        body: dict[str, Any] = {"kind": kind, "rating": rating, "comment": comment, **context}
        return await self.post("/api/feedback", body)

    async def browse(self) -> dict[str, Any]:
        return await self.get("/api/browse")

    async def read_file(self, path: str) -> dict[str, Any]:
        return await self._request("GET", "/api/read", params={"path": path})

    async def get_raw(self, path: str) -> tuple[bytes, str]:
        """Binary passthrough (figures, PDFs) from hive's /api/raw."""
        headers = {"X-Hive-Token": self._token} if self._token else {}
        resp = await self._client.get(f"{self._base}/api/raw", params={"path": path}, headers=headers)
        if resp.status_code >= 400:
            raise HiveApiError("/api/raw", resp.status_code, resp.text[:200])
        return resp.content, resp.headers.get("content-type", "application/octet-stream")
