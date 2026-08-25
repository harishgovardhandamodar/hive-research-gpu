"""Tool registry: every capability of the main app the agent may invoke.

Each tool declares whether it mutates library state; autonomy modes use that
flag to decide what runs without approval.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from .hive_client import HiveApiError, HiveClient

if TYPE_CHECKING:
    from .ingest_failures import IngestFailureStore

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    mutates: bool = False
    handler: Callable[..., Any] = None  # type: ignore[assignment]
    args: dict[str, str] = field(default_factory=dict)

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "args": self.args, "mutates": self.mutates}


class ToolRegistry:
    def __init__(
        self,
        client: HiveClient,
        failures: IngestFailureStore | None = None,
        episodes: Any = None,
        llm: Any = None,
    ) -> None:
        self.client = client
        self.failures = failures
        self.episodes = episodes
        self.llm = llm
        self._tools: dict[str, Tool] = {}
        self._register_all()

    def _register(
        self,
        name: str,
        description: str,
        mutates: bool = False,
        args: dict[str, str] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            sig = inspect.signature(fn)
            kwargs = {p for p in sig.parameters if p != "self"}
            for arg in (args or {}):
                if arg not in kwargs:
                    raise ValueError(f"tool {name}: declared arg {arg!r} not in handler signature")
            self._tools[name] = Tool(
                name=name, description=description, mutates=mutates, handler=fn, args=args or {}
            )
            return fn

        return deco

    def _register_all(self) -> None:
        client = self.client

        @self._register("library.stats", "Counts of papers, notes, concepts and graph size.")
        async def _stats() -> Any:
            return await client.stats()

        @self._register(
            "library.list_papers",
            "List ingested papers with titles and note status.",
            args={"query": "optional title/keyword filter"},
        )
        async def _papers(query: str = "") -> Any:
            return await client.papers(query=query)

        @self._register(
            "library.search",
            "Search the local library by keyword; returns matches without ingesting.",
            args={"query": "keyword query"},
        )
        async def _search(query: str) -> Any:
            return await client.paper_search(query)

        @self._register("rag.query", "Grounded question answering over indexed paper notes.", args={"question": "the research question"})
        async def _rag_query(question: str) -> Any:
            return await client.rag_query(question)

        @self._register("graph.clusters", "Similarity clusters of the knowledge graph — themes in the library.")
        async def _clusters() -> Any:
            return await client.graph_clusters()

        @self._register("graph.similarity", "Compare specific papers by id.", args={"paper_ids": "comma-separated arxiv ids"})
        async def _similarity(paper_ids: str) -> Any:
            ids = [x.strip() for x in paper_ids.split(",") if x.strip()]
            return await client.similarity(ids)

        @self._register("pool.papers", "Papers observed in the watch pool, not yet imported.")
        async def _pool_papers() -> Any:
            return await client.pool_papers()

        @self._register("pool.topics", "Topics currently watched by the pool.")
        async def _pool_topics() -> Any:
            return await client.pool_topics()

        @self._register(
            "library.add_paper",
            "Ingest one arxiv paper by id: download PDF, extract, write notes, index.",
            mutates=True,
            args={"arxiv_id": "arxiv identifier, e.g. 2401.12345"},
        )
        async def _add(arxiv_id: str) -> Any:
            return await client.add_paper(arxiv_id)

        @self._register(
            "library.retry_failed",
            "Re-ingest papers whose previous ingestion failed, one by one.",
            mutates=True,
        )
        async def _retry_failed() -> Any:
            if self.failures is None:
                return {"retried": 0, "message": "failure ledger unavailable"}
            ids = [i["arxiv_id"] for i in self.failures.items()]
            if not ids:
                return {"retried": 0, "message": "no failed ingestions to retry"}
            results = []
            recovered = 0
            for aid in ids:
                try:
                    res = await client.add_paper(aid)
                except HiveApiError as exc:
                    res = {"status": "error", "error": str(exc)}
                ok = isinstance(res, dict) and res.get("status") == "added"
                if ok:
                    self.failures.record_success(aid)
                    recovered += 1
                else:
                    self.failures.record_failure(aid, error=str(res.get("error", "")) if isinstance(res, dict) else "")
                results.append({"arxiv_id": aid, "status": res.get("status") if isinstance(res, dict) else "?"})
            return {"retried": len(ids), "recovered": recovered, "still_failed": len(ids) - recovered, "results": results}

        @self._register(
            "library.import_query",
            "Search arxiv for a query and ingest the best matches.",
            mutates=True,
            args={"query": "arxiv search query", "model": "optional LLM model override"},
        )
        async def _import(query: str, model: str = "") -> Any:
            return await client.import_query(query, model=model or None)

        @self._register(
            "notes.refresh_paper",
            "Re-analyze one paper's notes with a fresh model pass.",
            mutates=True,
            args={"paper_id": "arxiv id"},
        )
        async def _refresh_paper(paper_id: str) -> Any:
            return await client.refresh_paper(paper_id)

        @self._register("notes.refresh_all", "Re-analyze all papers.", mutates=True)
        async def _refresh_all() -> Any:
            return await client.refresh_all()

        @self._register("rag.rebuild", "Rebuild the RAG vector index from all notes.", mutates=True)
        async def _rag_rebuild() -> Any:
            return await client.rag_rebuild()

        @self._register(
            "improve.run",
            "Close the reinforcement loop: re-analyze papers whose notes were rated poorly.",
            mutates=True,
        )
        async def _improve() -> Any:
            return await client.improve_run()

        @self._register(
            "survey.start",
            "Start a background survey-report job on a topic.",
            mutates=True,
            args={"topic": "survey topic"},
        )
        async def _survey(topic: str) -> Any:
            return await client.fox_survey(topic)

        @self._register(
            "pool.import_topic",
            "Import matching pool papers for a watched topic into the library.",
            mutates=True,
            args={"topic": "watched topic", "max_results": "cap on imports"},
        )
        async def _pool_import(topic: str, max_results: int = 0) -> Any:
            return await client.pool_import(topic, max_results or None)

        @self._register("fox.chat", "Conversational grounded answer via Fox companion modes.", args={"message": "user message", "mode": "fast|rag|thinking|deep-thinking|deep-research"})
        async def _fox_chat(message: str, mode: str = "rag") -> Any:
            return await client.fox_chat(message, mode=mode)

        @self._register("feedback.summary", "Summary of researcher ratings and criticism so far.")
        async def _feedback_summary() -> Any:
            return await client.feedback_summary()

        @self._register("digest.daily", "What changed across the vault recently.")
        async def _digest() -> Any:
            return await client.digest()

        @self._register("system.jobs", "Currently running background jobs.")
        async def _jobs() -> Any:
            return await client.jobs()

        @self._register("system.gpu", "GPU status and utilization.")
        async def _gpu() -> Any:
            return await client.gpu()

        @self._register(
            "memory.reflect",
            "Consolidate recent episodic memory into durable research insights (Generative-Agents style reflection).",
            mutates=True,
        )
        async def _reflect() -> Any:
            if self.episodes is None or self.llm is None:
                return {"consolidated": 0, "message": "memory reflection unavailable"}
            recent = self.episodes.recent(limit=200)
            if len(recent) < 10:
                return {"consolidated": 0, "message": "not enough episodes to reflect on yet"}
            transcript = "\n".join(f"[{e['kind']}] {e['summary']}" for e in recent[-120:])[:6000]
            content = await self.llm.chat(
                system=(
                    "Distill this research-agent activity log into at most 5 durable insights about "
                    "the researcher's interests, workflows and quality patterns. "
                    'Respond exactly as {"insights": ["...", ...]}.'
                ),
                user=transcript,
                json_mode=True,
                num_predict=400,
            )
            import json as _json
            import re as _re

            match = _re.search(r"\{.*\}", content, re.DOTALL)
            insights = _json.loads(match.group(0)).get("insights", []) if match else []
            made = 0
            for text in insights[:5]:
                if isinstance(text, str) and text.strip():
                    self.episodes.append("insight", text.strip()[:400])
                    made += 1
            return {"consolidated": made, "reviewed_episodes": len(recent)}

        @self._register(
            "verify.attribution",
            "Check that arxiv ids cited in a vault note actually exist in the library — anti-hallucination pass.",
            args={"path": "vault-relative note path"},
        )
        async def _verify_attribution(path: str) -> Any:
            from .kg import extract_arxiv_ids

            file = await client.read_file(path)
            ids = extract_arxiv_ids(file.get("content", ""), limit=25)
            if not ids:
                return {"checked": 0, "missing": [], "message": "no arxiv references found in the note"}
            library = {str(p.get("arxiv_id", p.get("id", ""))) for p in await client.papers()}
            bases = {i.split("v")[0] for i in library}
            missing = [i for i in ids if i.split("v")[0] not in bases]
            return {"checked": len(ids), "known": len(ids) - len(missing), "missing": missing}

        @self._register(
            "pool.watch_topic",
            "Add a topic to the arxiv watch pool.",
            mutates=True,
            args={"topic": "topic phrase"},
        )
        async def _watch(topic: str) -> Any:
            return await client.pool_topic_add(topic)

    # -- accessors -----------------------------------------------------------

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"status": "error", "error": f"unknown tool: {name}"}
        filtered = {k: v for k, v in (args or {}).items() if k in tool.handler.__code__.co_varnames}
        try:
            result = await tool.handler(**filtered)
            return {"status": "ok", "tool": name, "result": _shrink(result)}
        except HiveApiError as exc:
            logger.warning("tool %s failed: %s", name, exc)
            return {"status": "error", "tool": name, "error": str(exc)}

    def is_mutating(self, name: str) -> bool:
        tool = self._tools.get(name)
        return bool(tool and tool.mutates)


def _shrink(result: Any, max_items: int = 20) -> Any:
    """Cap large lists/dicts so plan events stay renderable."""
    if isinstance(result, list) and len(result) > max_items:
        return {"items": result[:max_items], "total": len(result), "truncated": True}
    if isinstance(result, dict):
        out = {}
        for key, value in result.items():
            if isinstance(value, list) and len(value) > max_items:
                out[key] = {"items": value[:max_items], "total": len(value), "truncated": True}
            else:
                out[key] = value
        return out
    return result
