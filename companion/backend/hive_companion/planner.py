"""Planner: turn a research goal into a concrete, validated tool plan.

Primary path is LLM-driven (tool specs + episodic context + learned policy
hints in the prompt, JSON plan out). When the LLM is unavailable the heuristic
planner covers common goal shapes so the companion degrades gracefully.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .llm import ChatClient
from .policy import ReinforcementPolicy
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Step:
    index: int
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    state: str = "pending"  # pending|awaiting_approval|running|done|skipped|failed


@dataclass
class Plan:
    id: str
    goal_id: str
    goal: str
    steps: list[Step]
    planner: str = "heuristic"
    status: str = "ready"  # ready|running|done|failed|cancelled
    created_by_agent: str = ""  # agent profile that shaped this plan

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        steps = [Step(**s) for s in data.get("steps", [])]
        return cls(
            id=data["id"],
            goal_id=data["goal_id"],
            goal=data["goal"],
            steps=steps,
            planner=data.get("planner", "heuristic"),
            status=data.get("status", "ready"),
        )


def _validate_steps(raw_steps: list[Any], registry: ToolRegistry) -> tuple[list[Step], list[str]]:
    steps: list[Step] = []
    dropped: list[str] = []
    for i, raw in enumerate(raw_steps):
        if isinstance(raw, str):
            raw = {"tool": raw.strip(), "args": {}}
        elif not isinstance(raw, dict):
            dropped.append(f"step {i} (invalid type {type(raw).__name__})")
            continue
        name = str(raw.get("tool", "")).strip()
        tool = registry.get(name)
        if tool is None:
            dropped.append(name or f"step {i}")
            continue
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        missing = [a for a in tool.args if a not in args]
        if missing:
            dropped.append(f"{name} (missing {', '.join(missing)})")
            continue
        steps.append(
            Step(
                index=len(steps),
                tool=name,
                args=args,
                rationale=str(raw.get("rationale", ""))[:300],
            )
        )
    return steps[:8], dropped


class Planner:
    def __init__(self, registry: ToolRegistry, llm: ChatClient | None, policy: ReinforcementPolicy) -> None:
        self.registry = registry
        self.llm = llm
        self.policy = policy

    async def build(self, goal_text: str, memory_context: str = "") -> Plan:
        plan_id = uuid.uuid4().hex[:12]
        raw_steps: list[dict[str, Any]] | None = None
        used = "heuristic"
        if self.llm is not None:
            try:
                raw_steps = await self._plan_with_llm(goal_text, memory_context)
                used = "llm"
            except Exception as exc:
                logger.warning("LLM planning failed (%s); using heuristics", exc)
        if raw_steps is None:
            raw_steps = self._plan_heuristic(goal_text)
        steps, dropped = _validate_steps(raw_steps, self.registry)
        # -- deterministic fix for graph snapshot intents (LLM often confuses save/load/list)
        lower = goal_text.lower()
        has_snapshot = "snapshot" in lower or "snapshots" in lower
        has_graph = "graph" in lower or "knowledge graph" in lower
        if has_snapshot or has_graph:
            wants_list = "list" in lower and "snapshot" in lower
            wants_save = "save" in lower and has_snapshot
            wants_load = "load" in lower and has_snapshot
            has_list = any(s.tool == "graph.list_snapshots" for s in steps)
            has_save = any(s.tool == "graph.save" for s in steps)
            has_load = any(s.tool == "graph.load" for s in steps)
            if wants_list and not has_list:
                steps = [Step(index=0, tool="graph.list_snapshots", args={}, rationale="list snapshots (deterministic heuristic)")]
                logger.info("heuristic override: list snapshots -> graph.list_snapshots")
            elif wants_save and not has_save:
                m = re.search(r"(?:save|as)\s+([A-Za-z0-9._-]+)", goal_text, re.I)
                name = m.group(1) if m else "snapshot"
                # try to find quoted name
                q = re.search(r'"([^"]+)"|\'([^\']+)\'', goal_text)
                if q:
                    name = (q.group(1) or q.group(2)).strip()
                steps = [Step(index=0, tool="graph.save", args={"name": name}, rationale=f"save snapshot as {name}")]
                logger.info("heuristic override: save -> graph.save %s", name)
            elif wants_load and not has_load:
                m = re.search(r"(?:load|snapshot)\s+([A-Za-z0-9._-]+)", goal_text, re.I)
                name = m.group(1) if m else ""
                q = re.search(r'"([^"]+)"|\'([^\']+)\'', goal_text)
                if q:
                    name = (q.group(1) or q.group(2)).strip()
                # fallback: last word that looks like snapshot name
                if not name or name.lower() in ("snapshot", "snapshots", "graph", "knowledge"):
                    # try to extract after "load" 
                    m2 = re.search(r"load\s+(?:the\s+)?(?:knowledge\s+graph\s+snapshot\s+)?([A-Za-z0-9._-]+)", goal_text, re.I)
                    if m2:
                        name = m2.group(1)
                if name and name.lower() not in ("snapshot", "snapshots", "graph"):
                    steps = [Step(index=0, tool="graph.load", args={"name": name}, rationale=f"load snapshot {name}")]
                    logger.info("heuristic override: load -> graph.load %s", name)
        if not steps:
            fallback_tool = "fox.chat"
            steps = [
                Step(index=0, tool=fallback_tool, args={"message": goal_text}, rationale="fallback conversational answer")
            ]
        if dropped:
            logger.info("dropped invalid steps: %s", dropped)
        plan = Plan(id=plan_id, goal_id="", goal=goal_text, steps=steps, planner=used)

        # Tree-of-Thought lite: sample alternative drafts and keep the
        # highest critic score instead of committing to the first attempt.
        if used == "llm":
            best_score, alternatives = None, []
            for _ in range(self.BEST_OF_N - 1):
                try:
                    alt_raw = await self._plan_with_llm(goal_text, memory_context)
                    alt, _d = _validate_steps(alt_raw, self.registry)
                    if alt:
                        alternatives.append(alt)
                except Exception:
                    continue
            for alt in alternatives:
                score = await self._score_plan(goal_text, alt)
                if best_score is None or score > best_score[0]:
                    best_score = (score, alt)
            if best_score and alternatives:
                current = await self._score_plan(goal_text, plan.steps)
                if best_score[0] > current + 0.5:
                    plan.steps = [
                        Step(index=n, tool=s.tool, args=s.args, rationale=s.rationale)
                        for n, s in enumerate(best_score[1])
                    ]
                    plan.planner = "llm-tot"
                    logger.info("best-of-N: switched to higher-scored draft (%.1f > %.1f)", best_score[0], current)

        if used == "llm":
            await self._critique(plan)
        # final deterministic correction for graph snapshot intents (after best-of-N/critique may have reintroduced wrong tool)
        lower2 = goal_text.lower()
        has_snapshot2 = "snapshot" in lower2 or "snapshots" in lower2
        has_graph2 = "graph" in lower2 or "knowledge graph" in lower2
        if has_snapshot2 or has_graph2:
            wants_list2 = "list" in lower2 and "snapshot" in lower2
            wants_save2 = "save" in lower2 and has_snapshot2
            wants_load2 = "load" in lower2 and has_snapshot2
            has_list2 = any(s.tool == "graph.list_snapshots" for s in plan.steps)
            has_save2 = any(s.tool == "graph.save" for s in plan.steps)
            has_load2 = any(s.tool == "graph.load" for s in plan.steps)
            if wants_list2 and not has_list2:
                plan.steps = [Step(index=0, tool="graph.list_snapshots", args={}, rationale="list snapshots (final correction)")]
                logger.info("final correction: list snapshots -> graph.list_snapshots")
            elif wants_save2 and not has_save2:
                m = re.search(r"save(?:\s+as)?\s+([A-Za-z0-9._-]+)", goal_text, re.I)
                name = m.group(1) if m else "snapshot"
                q = re.search(r'"([^"]+)"|\'([^\']+)\'', goal_text)
                if q:
                    name = (q.group(1) or q.group(2)).strip()
                plan.steps = [Step(index=0, tool="graph.save", args={"name": name}, rationale=f"save snapshot as {name}")]
                logger.info("final correction: save -> graph.save %s", name)
            elif wants_load2 and not has_load2:
                m = re.search(r"load(?:\s+snapshot)?\s+([A-Za-z0-9._-]+)", goal_text, re.I)
                if not m:
                    m = re.search(r"snapshot\s+([A-Za-z0-9._-]+)", goal_text, re.I)
                name = m.group(1) if m else ""
                q = re.search(r'"([^"]+)"|\'([^\']+)\'', goal_text)
                if q:
                    name = (q.group(1) or q.group(2)).strip()
                if not name or name.lower() in ("snapshot", "snapshots", "graph", "knowledge"):
                    m2 = re.search(r"load\s+(?:the\s+)?(?:knowledge\s+graph\s+snapshot\s+)?([A-Za-z0-9._-]+)", goal_text, re.I)
                    if m2:
                        name = m2.group(1)
                if name and name.lower() not in ("snapshot", "snapshots", "graph"):
                    plan.steps = [Step(index=0, tool="graph.load", args={"name": name}, rationale=f"load snapshot {name}")]
                    logger.info("final correction: load -> graph.load %s", name)
        return plan

    BEST_OF_N = 2  # total drafts considered (original + N-1 alternatives)

    async def _score_plan(self, goal_text: str, steps: list) -> float:
        """Critic score 0-10 for a candidate plan (0 when scoring unavailable)."""
        if self.llm is None or not steps:
            return 0.0
        try:
            listing = "\n".join(f"{i}: {s.tool} {json.dumps(s.args)[:80]}" for i, s in enumerate(steps))
            content = await self.llm.chat(
                system=(
                    "Rate this research-agent plan for the given goal from 0 (useless) "
                    'to 10 (excellent). Respond exactly as {"score": <number>}.'
                ),
                user=f"Goal: {goal_text}\nPlan:\n{listing}",
                json_mode=True,
                num_predict=40,
            )
            match = re.search(r"\{.*\}", content, re.DOTALL)
            return float(json.loads(match.group(0)).get("score", 0)) if match else 0.0
        except Exception:
            return 0.0

    async def _critique(self, plan: Plan) -> None:
        """LLM-as-critic pre-flight: drop redundant/off-goal steps before execution.

        Self-Refine-style second pass — the planner drafts, the critic trims.
        Failures here are non-fatal; a bad critique just means we run as planned.
        """
        if self.llm is None or len(plan.steps) < 2:
            return
        try:
            listing = "\n".join(
                f"{i}: {s.tool} {json.dumps(s.args)}" for i, s in enumerate(plan.steps)
            )
            content = await self.llm.chat(
                system=(
                    "You are a plan critic. Given a goal and numbered plan steps, "
                    'return exactly {"drop": [<step indices to remove>]} — only steps that are '
                    "redundant, off-goal, or duplicated. Drop nothing when the plan is tight."
                ),
                user=f"Goal: {plan.goal}\nSteps:\n{listing}",
                json_mode=True,
                num_predict=120,
            )
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return
            drop = [int(i) for i in json.loads(match.group(0)).get("drop", [])]
            keep = [s for i, s in enumerate(plan.steps) if i not in drop]
            if not keep or len(keep) == len(plan.steps):
                return
            logger.info("critic dropped steps %s from plan", drop)
            plan.steps = [
                Step(index=n, tool=s.tool, args=s.args, rationale=s.rationale)
                for n, s in enumerate(keep)
            ]
        except Exception as exc:
            logger.debug("plan critic skipped: %s", exc)

    # -- LLM path ------------------------------------------------------------

    def _system_prompt(self) -> str:
        hints = self.policy.planner_hints()
        return (
            "You are the planning module of a research companion agent. "
            "Given a researcher's goal, produce a short JSON plan using ONLY the listed tools. "
            'Respond exactly as {"steps": [{"tool": "<name>", "args": {...}, "rationale": "..."}]}. '
            "Prefer read-only tools first to gather facts, then mutating tools. Keep plans under 6 steps.\n"
            + (f"\nLearned preferences:\n{hints}\n" if hints else "")
        )

    async def _plan_with_llm(self, goal_text: str, memory_context: str) -> list[dict[str, Any]]:
        assert self.llm is not None
        specs = json.dumps(self.registry.specs(), indent=1)
        memory = f"\nRelevant past episodes:\n{memory_context}\n" if memory_context else ""
        content = await self.llm.chat(
            system=self._system_prompt(),
            user=f"Researcher goal: {goal_text}\nTools:\n{specs}{memory}",
            json_mode=True,
            num_predict=600,
        )
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("no JSON in planner output")
        data = json.loads(match.group(0))
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("planner produced no steps")
        return steps

    # -- heuristic path ------------------------------------------------------

    def _plan_heuristic(self, goal: str) -> list[dict[str, Any]]:
        text = goal.lower()
        steps: list[dict[str, Any]] = []

        def add(tool: str, args: dict[str, Any], why: str) -> None:
            steps.append({"tool": tool, "args": args, "rationale": why})

        topic = re.sub(r"^(write|do|make|run|start)\s+(a\s+)?(survey|review)\s*(on|about|of)?\s*", "", goal.strip(), flags=re.I).strip() or goal.strip()

        if re.search(r"\bsurvey\b|\bliterature review\b|\breview of\b", text):
            add("library.search", {"query": topic}, "check what the library already holds on the topic")
            add("survey.start", {"topic": topic}, "launch background survey report")
            add("digest.daily", {}, "summarize what changed afterwards")
        elif re.search(r"\bfind\b.*papers|\bimport\b|\bingest\b|\badd papers?\b|\barxiv\b", text):
            add("library.search", {"query": topic}, "avoid duplicates already in library")
            add("library.import_query", {"query": topic}, "ingest fresh matches from arxiv")
        elif re.search(r"\bimprove\b|\bbetter notes\b|\bre-?analy[sz]e\b|\breinforce", text):
            add("feedback.summary", {}, "see what the researcher rated poorly")
            add("improve.run", {}, "re-analyze low-rated notes with criticism injected")
        elif re.search(r"\brebuild\b|\bindex\b", text) and "rag" in text or "vector" in text:
            add("rag.rebuild", {}, "rebuild vector index")
        elif re.search(r"\bcompare\b|\bsimilar\b|\brelated\b", text):
            ids = re.findall(r"\d{4}\.\d{4,5}", goal)
            if len(ids) >= 2:
                add("graph.similarity", {"paper_ids": ",".join(ids)}, "compare the given papers")
            else:
                add("graph.clusters", {}, "cluster view to locate related work")
        elif re.search(r"what.?s new|\bdigest\b|\bupdate me\b|\bstatus\b", text):
            add("library.stats", {}, "current library state")
            add("digest.daily", {}, "recent changes digest")
        elif re.search(r"\bpool\b|\bwatch\b|\btopic", text) and re.search(r"\bimport\b|\bpull\b|\bsync\b", text):
            add("pool.topics", {}, "list watched topics")
            add("pool.import_topic", {"topic": topic}, "import matching pool papers")
        elif re.search(r"\blist\b.*snapshot|\bsnapshots\b", text):
            add("graph.list_snapshots", {}, "list saved graph snapshots")
        elif re.search(r"\bsave\b.*(?:graph|snapshot)|\bsnapshot\b.*save", text):
            m = re.search(r"save(?:\s+as)?\s+([A-Za-z0-9._-]+)", goal, re.I)
            name = m.group(1) if m else "snapshot"
            q = re.search(r'"([^"]+)"|\'([^\']+)\'', goal)
            if q:
                name = (q.group(1) or q.group(2)).strip()
            add("graph.save", {"name": name}, f"save graph snapshot as {name}")
        elif re.search(r"\bload\b.*(?:graph|snapshot)|\brestore\b.*(?:graph|snapshot)", text):
            m = re.search(r"load(?:\s+snapshot)?\s+([A-Za-z0-9._-]+)", goal, re.I)
            if not m:
                m = re.search(r"snapshot\s+([A-Za-z0-9._-]+)", goal, re.I)
            name = m.group(1) if m else ""
            q = re.search(r'"([^"]+)"|\'([^\']+)\'', goal)
            if q:
                name = (q.group(1) or q.group(2)).strip()
            if name and name.lower() not in ("snapshot", "snapshots", "graph"):
                add("graph.load", {"name": name}, f"load graph snapshot {name}")
            else:
                add("graph.list_snapshots", {}, "list snapshots to discover name to load")
        else:
            add("rag.query", {"question": goal}, "grounded answer over indexed notes")
            add("fox.chat", {"message": goal, "mode": "fast"}, "conversational synthesis when retrieval is thin")
        return steps
