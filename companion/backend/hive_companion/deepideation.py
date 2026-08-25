"""Deep Ideation agent: novel research ideas from the scientific concept network.

Inspired by "Deep Ideation" (arXiv 2504.10153): instead of archiving by
descriptors, this agent *traverses* the library's concept network — picking a
seed concept, walking to a related neighbour, then applying the paper's core
moves:

- backward thinking  : ground the pair in their foundational principles
- forward thinking   : project where the pair points next
- recursive refinement: critique-and-revise the draft against existing work

Each run explores several (seed, bridge) concept pairs and returns refined,
scored ideas annotated with their concept chain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .kg import KGCache
from .ideagent import overall, _clamp, _parse_json, utcnow
from .llm import ChatClient

logger = logging.getLogger(__name__)

_GEN_SYSTEM = (
    "You are Deep Ideation, an agent that generates novel research ideas by "
    "bridging two scientific concepts from a researcher's concept network. "
    "Respond ONLY as JSON: "
    '{"title": "...", "summary": "3-4 sentence pitch: mechanism, why the '
    'bridge is non-obvious, evaluation plan", "mechanism": "the core method '
    'in <=12 words", "builds_on": ["concept A", "concept B"]}'
)

_BACKWARD_SYSTEM = (
    "You trace foundational principles. Given two scientific concepts, state "
    "the single deepest shared principle they rest on. One sentence only."
)

_FORWARD_SYSTEM = (
    "You project emerging directions. Given two scientific concepts, name the "
    "most under-explored direction they jointly point toward. One sentence."
)

_CRITIQUE_SYSTEM = (
    "You are a novelty auditor. Given an idea draft and evidence of similar "
    "existing work in the researcher's library, identify the weakest novelty "
    "claim and suggest one concrete revision that strengthens it. Respond ONLY "
    'as JSON: {"critique": "...", "revised_title": "...", "revised_summary": "..."}'
)

_JUDGE_SYSTEM = (
    "You are a harsh but fair research reviewer. Score the idea. Respond ONLY "
    'as JSON: {"novelty": 0-10, "feasibility": 0-10, "impact": 0-10, '
    '"verdict": "one line"}'
)


def _tokens(text: str) -> set[str]:
    return {t for t in re_split(text) if len(t) > 2}


def re_split(text: str) -> list[str]:
    out, cur = [], ""
    for ch in text.lower():
        if ch.isalnum():
            cur += ch
        else:
            if cur:
                out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


class ConceptNetwork:
    """Co-occurrence network over the KG's concept nodes."""

    def __init__(self, kg: KGCache) -> None:
        self.kg = kg
        self._built_at = 0.0
        self.labels: dict[str, str] = {}
        self.definitions: dict[str, str] = {}
        self.neighbours: dict[str, dict[str, int]] = defaultdict(dict)
        self.paper_titles: dict[str, list[str]] = defaultdict(list)

    def refresh(self, force: bool = False) -> bool:
        if not force and time.time() - self._built_at < 300:
            return True
        try:
            g = self.kg._graph if self.kg._graph else {}
            if not g:
                return False
        except Exception:
            return False
        nodes = {n["id"]: n for n in g.get("nodes", [])}
        concepts = {i for i, n in nodes.items() if n.get("type") == "concept"}
        self.labels = {i: nodes[i].get("label", i) for i in concepts}
        self.definitions = {
            i: nodes[i]["definition"][:200] for i in concepts if nodes[i].get("definition")
        }
        paper_concepts: dict[str, list[str]] = defaultdict(list)
        for l in g.get("links", []):
            s, t = l["source"], l["target"]
            if s in concepts and t not in concepts:
                paper_concepts[t].append(s)
            elif t in concepts and s not in concepts:
                paper_concepts[s].append(t)
        for pc, cs in paper_concepts.items():
            title = nodes.get(pc, {}).get("title") or nodes.get(pc, {}).get("label")
            for i, a in enumerate(cs):
                for b in cs[i + 1:]:
                    self.neighbours[a][b] = self.neighbours[a].get(b, 0) + 1
                    self.neighbours[b][a] = self.neighbours[b].get(a, 0) + 1
                if title:
                    self.paper_titles[(a, b)].append(str(title)[:80])
        self._built_at = time.time()
        return True

    def seeds_for(self, topic: str, n: int = 3) -> list[str]:
        q = set(_tokens(topic))
        scored = []
        for cid, label in self.labels.items():
            overlap = len(q & set(_tokens(label)))
            degree = len(self.neighbours.get(cid, {}))
            scored.append((overlap * 3 + min(degree, 8) * 0.1, cid))
        scored.sort(reverse=True)
        return [cid for _, cid in scored[:n] if True]

    def bridge_for(self, seed: str, used: set[str], distant_bias: float = 0.0) -> str | None:
        nbrs = {
            b: w
            for b, w in self.neighbours.get(seed, {}).items()
            if b not in used
        }
        if not nbrs:
            return None
        # mix: usually strongest co-occurrence; occasionally a weaker link
        ranked = sorted(nbrs.items(), key=lambda kv: kv[1])
        if distant_bias > 0 and len(ranked) > 2:
            idx = int(distant_bias * (len(ranked) - 1))
            return ranked[idx][0]
        return ranked[-1][0]

    def evidence(self, a: str, b: str) -> list[str]:
        titles = self.paper_titles.get((a, b)) or self.paper_titles.get((b, a)) or []
        return titles[:3]

    def chain_label(self, a: str, b: str) -> str:
        la = self.labels.get(a, a)
        lb = self.labels.get(b, b)
        return f"{la} → {lb}"


class DeepRun:
    def __init__(self, topic: str, iterations: int, depth: int) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.topic = topic
        self.iterations = iterations
        self.depth = depth
        self.status = "running"
        self.started = utcnow().isoformat()
        self.finished: str | None = None
        self.error: str | None = None
        self.ideas: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
            "iterations": self.iterations,
            "depth": self.depth,
            "candidates_seen": len(self.events),
            "ideas": sorted(self.ideas, key=lambda i: i.get("overall", 0), reverse=True),
        }


class DeepIdeationEngine:
    def __init__(
        self,
        llm_fast: ChatClient | None,
        llm_main: ChatClient | None,
        kg: KGCache,
        network: ConceptNetwork,
        bus: Any = None,
        on_complete: Any = None,
        on_iteration: Any = None,
        search_fn: Any = None,
    ) -> None:
        self.llm_fast = llm_fast
        self.llm_main = llm_main
        self.kg = kg
        self.network = network
        self.bus = bus
        self.on_complete = on_complete
        self.on_iteration = on_iteration
        self.search_fn = search_fn  # async fn(query) -> list[dict] of library hits
        self.active: DeepRun | None = None
        self.history: list[DeepRun] = []

    def resolve_llm(self, model: str) -> ChatClient | None:
        if model == "main":
            return self.llm_main or self.llm_fast
        return self.llm_fast or self.llm_main

    async def run(
        self,
        topic: str,
        iterations: int = 5,
        depth: int = 2,
        model: str = "fast",
        wait: bool = False,
    ) -> DeepRun:
        if self.active is not None and self.active.status == "running":
            raise RuntimeError("a run is already active")
        llm = self.resolve_llm(model)
        if llm is None:
            raise RuntimeError("no LLM available for ideation")
        try:
            await self.kg.get()  # prime the cached graph
        except Exception as exc:
            logger.warning("kg priming failed: %s", exc)
        run = DeepRun(topic, max(2, min(iterations, 12)), max(0, min(depth, 3)))
        self.active = run
        self.history.append(run)
        if wait:
            await self._execute(run, llm)
        else:
            asyncio.create_task(self._execute(run, llm))
        return run

    async def _execute(self, run: DeepRun, llm: ChatClient) -> None:
        try:
            if not self.network.refresh(force=False) and not self.network.labels:
                raise RuntimeError("concept network unavailable")
            used: set[str] = set()
            seeds = self.network.seeds_for(run.topic, n=max(3, run.iterations))

            # precompute unique (seed, bridge) pairs across all seeds,
            # strongest co-occurrence first
            pair_list: list[tuple[str, str]] = []
            seen_pairs: set[frozenset] = set()
            for seed in seeds:
                for bridge, _w in sorted(
                    self.network.neighbours.get(seed, {}).items(),
                    key=lambda kv: -kv[1],
                ):
                    key = frozenset((seed, bridge))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    pair_list.append((seed, bridge))
            pair_list = pair_list[: run.iterations]

            consecutive_failures = 0
            failed_pairs = 0
            last_error = ""
            i = 0
            while i < len(pair_list) and consecutive_failures < 3:
                seed, bridge = pair_list[i]
                try:
                    await self._explore_pair(run, llm, seed, bridge)
                    consecutive_failures = 0
                except Exception as exc:
                    consecutive_failures += 1
                    failed_pairs += 1
                    last_error = str(exc)[:300]
                    logger.warning("pair %s-%s failed (%d in a row): %s", seed, bridge, consecutive_failures, exc)
                i += 1
                await asyncio.sleep(0)
            if not run.ideas and failed_pairs:
                # zero explored pairs must not masquerade as a finished search
                run.status = "failed"
                run.error = f"all {failed_pairs} explored pairs failed; last error: {last_error or 'unknown'}"
            else:
                run.status = "done"
        except asyncio.CancelledError:
            run.status = "cancelled"
            raise
        except Exception as exc:
            logger.exception("deep ideation run failed")
            run.status = "failed"
            run.error = str(exc)[:300]
        finally:
            run.finished = utcnow().isoformat()
            if self.active is run:
                self.active = None
            if self.on_complete:
                try:
                    self.on_complete(run)
                except Exception:
                    logger.exception("on_complete failed")

    async def _explore_pair(self, run: DeepRun, llm: ChatClient, a: str, b: str) -> None:
        la, lb = self.network.labels.get(a, a), self.network.labels.get(b, b)
        da = self.network.definitions.get(a, "")
        db = self.network.definitions.get(b, "")
        evidence = self.network.evidence(a, b)

        backward = await llm.chat(system=_BACKWARD_SYSTEM, user=f"{la} · {lb}", num_predict=120)
        forward = await llm.chat(system=_FORWARD_SYSTEM, user=f"{la} · {lb}", num_predict=120)

        user = (
            f"Bridge these two concepts into ONE research idea:\n"
            f"A: {la}" + (f" — {da}" if da else "") + "\n" +
            f"B: {lb}" + (f" — {db}" if db else "") + "\n\n"
            f"Foundational principle they share (backward thinking): {backward.strip()}\n"
            f"Emerging direction they point toward (forward thinking): {forward.strip()}\n"
            + (f"Evidence in the researcher's library:\n" + "\n".join(f"- {t}" for t in evidence) + "\n" if evidence else "")
        )
        content = await llm.chat(system=_GEN_SYSTEM, user=user, json_mode=True, num_predict=800, temperature=0.95)
        data = _parse_json(content)

        idea = {
            "id": uuid.uuid4().hex[:10],
            "title": str(data.get("title", ""))[:200] or f"Bridging {la} and {lb}",
            "summary": str(data.get("summary", ""))[:1400],
            "mechanism": str(data.get("mechanism", ""))[:120],
            "chain": [la, lb],
            "builds_on": [str(x)[:60] for x in (data.get("builds_on") or [])[:4]],
            "backward_principle": backward.strip()[:200],
            "forward_direction": forward.strip()[:200],
            "evidence_titles": evidence,
            "revisions": 0,
        }

        # multi-agent debate: an adversary makes the strongest case against
        # the draft before refinement — the critic then must answer it
        try:
            objection = await llm.chat(
                system=(
                    "You are a skeptical reviewer. In at most 3 sentences, deliver the "
                    "single strongest technical objection to this research idea "
                    "(feasibility, novelty, or evaluation). No pleasantries."
                ),
                user=f"{idea['title']}\n{idea['summary']}",
                num_predict=160,
            )
            idea["adversarial_objection"] = objection.strip()[:300]
        except Exception:
            objection = ""

        # recursive refinement: novelty check against the library, then revise
        for round_no in range(1, run.depth + 1):
            hits: list[str] = []
            if self.search_fn is not None:
                try:
                    found = await self.search_fn(" ".join(sorted(_tokens(idea["title"]))[:4]))
                except TypeError:
                    found = []
                except Exception:
                    found = []
                hits = [str(h.get("title", ""))[:70] for h in (found or [])][:3]
            critique_user = (
                f"Idea draft: {idea['title']}\n{idea['summary']}\n"
                + (f"Similar existing work in the library:\n" + "\n".join(f"- {h}" for h in hits) + "\n" if hits else "No close matches surfaced from the library.\n")
                + (f"A reviewer's strongest objection you MUST address:\n{objection}\n" if objection else "")
                + f"This is refinement round {round_no} of {run.depth}. Strengthen the weakest novelty claim."
            )
            try:
                crit_content = await llm.chat(system=_CRITIQUE_SYSTEM, user=critique_user, json_mode=True, num_predict=500)
                crit = _parse_json(crit_content)
                if crit.get("revised_title"):
                    idea["title"] = str(crit["revised_title"])[:200]
                if crit.get("revised_summary"):
                    idea["summary"] = str(crit["revised_summary"])[:1400]
                idea["revisions"] = round_no
                idea.setdefault("last_critique", str(crit.get("critique", ""))[:200])
            except Exception as exc:
                logger.warning("refinement round %d failed: %s", round_no, exc)

        judge_user = f"Idea: {idea['title']}\n{idea['summary']}"
        try:
            jcontent = await llm.chat(system=_JUDGE_SYSTEM, user=judge_user, json_mode=True, num_predict=300)
            jd = _parse_json(jcontent)
        except Exception:
            jd = {}
        n, f_, im = _clamp(jd, "novelty"), _clamp(jd, "feasibility"), _clamp(jd, "impact")
        idea.update({
            "novelty": round(n, 1),
            "feasibility": round(f_, 1),
            "impact": round(im, 1),
            "overall": overall(n, f_, im),
            "verdict": str(jd.get("verdict", ""))[:200],
        })
        run.ideas.append(idea)
        if self.on_iteration:
            try:
                self.on_iteration(run)
            except Exception:
                pass
        if self.bus is not None:
            self.bus.publish("deepidea", {"run_id": run.id, "title": idea["title"], "overall": idea["overall"]})
