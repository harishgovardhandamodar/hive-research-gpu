"""IDEAgent-style novel idea creation via Quality-Diversity search.

Inspired by "Agentic Quality-Diversity Search for Research Ideas"
(arXiv 2607.22375): maintain an archive of ideas organised by behaviour
descriptors — here *approach* (theoretical/empirical/systems/tooling) and
*risk* (incremental/bridging/radical). Each iteration generates a candidate
grounded in the researcher's library, asks the model to judge novelty,
feasibility and impact, and archives the best idea per descriptor cell.
Filling under-explored cells pushes the search toward genuinely diverse,
higher-risk ideas instead of converging on one safe suggestion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
from typing import Any, Awaitable, Callable

from .kg import KGCache
from .llm import ChatClient

logger = logging.getLogger(__name__)

APPROACHES = ["theoretical", "empirical", "systems", "tooling"]
RISKS = ["incremental", "bridging", "radical"]

_GEN_SYSTEM = (
    "You are a creative research-idea engine in the style of IDEAgent "
    "(quality-diversity search over research ideas). Given a research focus, "
    "library concepts and prior ideas, propose ONE genuinely novel, specific "
    "research idea. Respond ONLY as JSON: "
    '{"title": "...", "summary": "2-3 sentence pitch including method and '
    'evaluation plan", "approach": "theoretical|empirical|systems|tooling", '
    '"risk": "incremental|bridging|radical", '
    '"novelty": 0-10, "feasibility": 0-10, "impact": 0-10, '
    '"builds_on": ["concept", "concept"]}'
)

_JUDGE_SYSTEM = (
    "You are a harsh but fair research reviewer. Given an idea and the "
    "library context it will be measured against, respond ONLY as JSON: "
    '{"novelty": 0-10, "feasibility": 0-10, "impact": 0-10, "verdict": "one line"}'
)


def _parse_json(content: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("no JSON")
    data = json.loads(match.group(0))
    return data if isinstance(data, dict) else {}


def _clamp(data: dict[str, Any], key: str) -> float:
    try:
        return max(0.0, min(10.0, float(data.get(key, 0))))
    except (TypeError, ValueError):
        return 0.0


def overall(novelty: float, feasibility: float, impact: float) -> float:
    return round((novelty * 0.5 + feasibility * 0.25 + impact * 0.25) / 10, 3)


class IdeaRun:
    """State of one QD search execution."""

    def __init__(self, topic: str, iterations: int) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.topic = topic
        self.iterations = iterations
        self.status = "running"  # running | done | failed | cancelled
        self.started = datetime.now(timezone.utc).isoformat()
        self.finished: str | None = None
        self.error: str | None = None
        self.archive: dict[tuple[str, str], dict[str, Any]] = {}
        self.candidates: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        ideas = self.rank()
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
            "iterations": self.iterations,
            "archive_cells": len(APPROACHES) * len(RISKS),
            "cells_filled": len(self.archive),
            "candidates_seen": len(self.candidates),
            "ideas": ideas,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IdeaRun":
        r = cls(d.get("topic", ""), d.get("iterations", 0))
        r.id = d.get("id", uuid.uuid4().hex[:10])
        r.status = d.get("status", "done")
        r.started = d.get("started", utcnow().isoformat())
        r.finished = d.get("finished")
        r.error = d.get("error")
        n_candidates = int(d.get("candidates_seen", len(d.get("ideas", []))))
        r.candidates = [{"title": ""} for _ in range(n_candidates)]
        for idea in d.get("ideas", []):
            cell = tuple(idea.get("cell", "unknown/unknown").split("/"))
            r.archive[cell] = idea
        return r

    def rank(self) -> list[dict[str, Any]]:
        ideas = sorted(
            self.archive.values(),
            key=lambda i: i.get("overall", 0),
            reverse=True,
        )
        return ideas


def _bucket(value: str, options: list[str]) -> str:
    low = value.lower().strip()
    for opt in options:
        if opt in low:
            return opt
    return options[sum(ord(c) for c in value) % len(options)]


class IdeagentEngine:
    """Runs QD idea searches; one active run at a time."""

    def __init__(self, llm_fast: ChatClient | None, llm_main: ChatClient | None, kg: KGCache, bus: Any = None,
                 on_complete: Callable[[IdeaRun], None] | None = None,
                 on_iteration: Callable[[IdeaRun], None] | None = None) -> None:
        self.llm_fast = llm_fast
        self.llm_main = llm_main
        self.kg = kg
        self.bus = bus
        self.on_complete = on_complete
        self.on_iteration = on_iteration
        self.active: IdeaRun | None = None
        self.history: list[IdeaRun] = []

    def resolve_llm(self, model: str) -> ChatClient | None:
        if model == "main":
            return self.llm_main or self.llm_fast
        return self.llm_fast or self.llm_main

    async def run(self, topic: str, iterations: int = 8, model: str = "fast", wait: bool = False) -> IdeaRun:
        if self.active is not None and self.active.status == "running":
            raise RuntimeError("a run is already active")
        llm = self.resolve_llm(model)
        if llm is None:
            raise RuntimeError("no LLM available for ideation")

        run = IdeaRun(topic, max(2, min(iterations, 20)))
        self.active = run
        self.history.append(run)
        if wait:
            await self._execute(run, llm)
        else:
            asyncio.create_task(self._execute(run, llm))
        return run

    async def _execute(self, run: IdeaRun, llm: ChatClient) -> None:
        try:
            concepts = await self._library_concepts(run.topic)
            consecutive_failures = 0
            i = 0
            while i < run.iterations and consecutive_failures < 3:
                try:
                    candidate = await self._generate(run, llm, concepts)
                    judged = await self._ensure_scores(candidate, run, llm, concepts)
                    self._archive(run, judged, i)
                    if self.on_iteration:
                        try:
                            self.on_iteration(run)
                        except Exception:
                            pass
                    self.bus_publish(run, judged)
                    consecutive_failures = 0
                except Exception as exc:
                    consecutive_failures += 1
                    run.events.append({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "iteration": i + 1,
                        "kept": False,
                        "error": str(exc)[:160],
                    })
                    logger.warning("iteration %d failed (%d in a row): %s", i + 1, consecutive_failures, exc)
                i += 1
                await asyncio.sleep(0)
            run.status = "done"
        except asyncio.CancelledError:
            run.status = "cancelled"
            raise
        except Exception as exc:
            logger.exception("ideagent run failed")
            run.status = "failed"
            run.error = str(exc)[:300]
        finally:
            run.finished = datetime.now(timezone.utc).isoformat()
            if self.active is run:
                self.active = None
            if self.on_complete:
                try:
                    self.on_complete(run)
                except Exception:
                    logger.exception("on_complete failed")

    def bus_publish(self, run: IdeaRun, idea: dict[str, Any]) -> None:
        if self.bus is not None:
            self.bus.publish("idea", {"run_id": run.id, "title": idea["title"], "overall": idea["overall"]})

    async def _library_concepts(self, topic: str) -> list[str]:
        try:
            slim = self.kg.slim() if hasattr(self.kg, "slim") else {"nodes": []}
        except Exception:
            slim = {"nodes": []}
        tokens = _tokenize_set(topic)
        scored = []
        for n in slim.get("nodes", []):
            if n.get("type") != "concept":
                continue
            label = n["label"].lower()
            overlap = len(tokens & set(label.replace("-", " ").split()))
            scored.append((overlap, n["label"]))
        scored.sort(reverse=True)
        picked = [label for _, label in scored[:6]]
        if not picked:
            # fall back to any well-connected-looking concepts
            allc = [n["label"] for n in slim.get("nodes", []) if n.get("type") == "concept"]
            step = max(1, len(allc) // 6) if allc else 1
            picked = allc[::step][:6]
        return picked

    async def _generate(self, run: IdeaRun, llm: ChatClient, concepts: list[str]) -> dict[str, Any]:
        prior = [
            f"- {i['title']}" for i in run.rank()[-6:]
        ]
        empty_cells = [
            (a, r) for a in APPROACHES for r in RISKS if (a, r) not in run.archive
        ]
        target = empty_cells[(len(run.candidates)) % len(empty_cells)] if empty_cells else None
        target_line = (
            f"Target archive cell — approach: {target[0]}; risk: {target[1]}. "
            "Frame the idea to genuinely fit this descriptor."
            if target
            else "Pick whichever descriptor fits best."
        )
        user = (
            f"Research focus: {run.topic}\n"
            f"Library concepts (your work builds here): {', '.join(concepts)}\n"
            f"Prior ideas this session (STRICTLY FORBIDDEN to reuse their core mechanism or title wording):\n"
            + ("\n".join(prior) or "- none yet") + "\n"
            f"{target_line}\n"
            "Diversity rule: your idea must introduce a different PROBLEM FRAMING and a different CORE MECHANISM than every prior idea."
        )
        content = await llm.chat(system=_GEN_SYSTEM, user=user, json_mode=True, num_predict=700, temperature=0.95)
        data = _parse_json(content)
        approach = target[0] if target else _bucket(str(data.get("approach", "")), APPROACHES)
        risk = target[1] if target else _bucket(str(data.get("risk", "")), RISKS)
        candidate = {
            "id": uuid.uuid4().hex[:10],
            "title": str(data.get("title", ""))[:200] or "Untitled idea",
            "summary": str(data.get("summary", ""))[:1200],
            "approach": approach,
            "risk": risk,
            "builds_on": [str(x)[:60] for x in (data.get("builds_on") or [])[:5]],
            "iteration": len(run.candidates) + 1,
        }
        run.candidates.append({"title": candidate["title"], "risk": candidate["risk"]})
        return candidate

    async def _ensure_scores(
        self,
        candidate: dict[str, Any],
        run: IdeaRun,
        llm: ChatClient,
        concepts: list[str],
    ) -> dict[str, Any]:
        gen_scores = {
            "novelty": 5.0,
            "feasibility": 5.0,
            "impact": 5.0,
            "verdict": "",
        }
        try:
            judge_user = (
                f"Library context concepts: {', '.join(concepts)}\n"
                f"Idea: {candidate['title']}\n{candidate['summary']}"
            )
            content = await llm.chat(system=_JUDGE_SYSTEM, user=judge_user, json_mode=True, num_predict=300)
            data = _parse_json(content)
            gen_scores.update({k: data.get(k, v) for k, v in gen_scores.items() if k in data or k == "verdict"})
        except Exception:
            pass  # generator's implicit mid scores stand
        novelty, feasibility, impact = (
            _clamp(gen_scores, "novelty"),
            _clamp(gen_scores, "feasibility"),
            _clamp(gen_scores, "impact"),
        )
        candidate.update(
            {
                "novelty": round(novelty, 1),
                "feasibility": round(feasibility, 1),
                "impact": round(impact, 1),
                "overall": overall(novelty, feasibility, impact),
                "verdict": str(gen_scores.get("verdict", ""))[:200],
            }
        )
        return candidate

    def _archive(self, run: IdeaRun, idea: dict[str, Any], iteration: int) -> None:
        key = (idea["approach"], idea["risk"])
        incumbent = run.archive.get(key)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "iteration": iteration + 1,
            "cell": f"{key[0]}/{key[1]}",
            "title": idea["title"],
            "overall": idea["overall"],
            "kept": True,
        }
        if incumbent is None or idea["overall"] >= incumbent.get("overall", 0):
            run.archive[key] = {**idea, "cell": f"{key[0]}/{key[1]}"}
        else:
            event["kept"] = False
            event["incumbent_overall"] = incumbent.get("overall")
        run.events.append(event)


def _tokenize_set(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


def persist_runs(data_dir, history: list[IdeaRun], keep: int = 10) -> None:
    path = data_dir / "ideas.jsonl"
    lines = [json.dumps(r.to_dict(), default=str) for r in history[-keep:]]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines))
    import os

    os.replace(tmp, path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_s(start_ts: float) -> float:
    return round(time.time() - start_ts, 2)

# convenience used by tests/UI
def _attach_helpers() -> None:
    def cells_filled(self: IdeaRun) -> int:
        return len(self.archive)
    IdeaRun.cells_filled = cells_filled

_attach_helpers()
