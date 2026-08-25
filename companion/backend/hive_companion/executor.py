"""Plan execution with autonomy gating, approvals, memory and learning.

The executor walks a plan step by step. Under `approve` every mutating step
pauses until the researcher decides; under `tiered` only mutating steps pause;
under `auto` nothing pauses. Every step becomes an episodic-memory record and
every outcome updates the reinforcement policy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from .autonomy import AutonomyMode, gate
from .events import EventBus
from .episodic import EpisodeStore
from .planner import Plan, Step
from .policy import ReinforcementPolicy
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "approvals.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict[str, Any]] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for item in raw.get("pending", []):
            item["state"] = "stale"  # plans from a previous process are gone
            self._items[item["id"]] = item

    def _save(self) -> None:
        pending = [a for a in self._items.values() if a.get("status") == "pending"]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pending": pending}, indent=1))
        os.replace(tmp, self.path)

    def create(self, plan_id: str, step_index: int, tool: str, args: dict[str, Any], rationale: str) -> dict[str, Any]:
        approval = {
            "id": uuid.uuid4().hex[:12],
            "plan_id": plan_id,
            "step_index": step_index,
            "tool": tool,
            "args": args,
            "rationale": rationale,
            "status": "pending",
            "created": utcnow(),
        }
        with self._lock:
            self._items[approval["id"]] = approval
            self._save()
        return approval

    def resolve(self, approval_id: str, approved: bool, note: str = "") -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(approval_id)
            if not item or item.get("status") != "pending":
                return None
            item["status"] = "approved" if approved else "rejected"
            item["decided"] = utcnow()
            if note:
                item["note"] = note[:300]
            self._save()
        fut = self._futures.pop(approval_id, None)
        if fut and not fut.done():
            fut.set_result(approved)
        return item

    async def wait(self, approval_id: str, timeout_s: float) -> bool:
        with self._lock:
            item = self._items.get(approval_id)
            if item is None:
                return False
            if item.get("status") == "approved":
                return True
            if item.get("status") == "rejected":
                return False
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._futures[approval_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            with self._lock:
                self._futures.pop(approval_id, None)
                if item.get("status") == "pending":
                    item["status"] = "timeout"
                    self._save()
            return False

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in self._items.values() if a.get("status") == "pending"]

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self._items.values(), key=lambda a: a["created"])
        return [dict(a) for a in items[-limit:]]


class PlanExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        episodes: EpisodeStore,
        policy: ReinforcementPolicy,
        bus: EventBus,
        approvals: ApprovalStore,
        approval_timeout_s: float = 1800.0,
        max_mutations: int = 6,
        budget_s: float = 1800.0,
        judge: Any = None,
    ) -> None:
        self.registry = registry
        self.episodes = episodes
        self.policy = policy
        self.bus = bus
        self.approvals = approvals
        self.approval_timeout_s = approval_timeout_s
        self.timeout_s = approval_timeout_s
        self.max_mutations = max_mutations
        self.budget_s = budget_s
        self.judge = judge  # optional ChatClient used for success-criteria verdicts
        self.active: dict[str, Plan] = {}
        self._modes: dict[str, AutonomyMode] = {}

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.bus.publish(event_type, payload)

    def set_mode(self, plan_id: str, mode: AutonomyMode) -> bool:
        """Switch autonomy live; the runner re-reads this before every step."""
        if plan_id not in self.active:
            return False
        self._modes[plan_id] = mode
        return True

    async def run_plan(
        self,
        plan: Plan,
        goal_id: str,
        session_id: str,
        mode: AutonomyMode,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute steps, yielding one event per transition."""
        plan.status = "running"
        self.active[plan.id] = plan
        self._modes[plan.id] = mode
        queue: asyncio.Queue = asyncio.Queue()

        async def runner() -> None:
            try:
                await self._run_steps(plan, goal_id, session_id, queue)
            finally:
                await queue.put(None)
                self._modes.pop(plan.id, None)

        task = asyncio.create_task(runner())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            task.cancel()

    async def _run_steps(
        self,
        plan: Plan,
        goal_id: str,
        session_id: str,
        queue: asyncio.Queue,
    ) -> None:
        mode = self._modes.get(plan.id, AutonomyMode.TIERED)
        started = datetime.now(timezone.utc)
        mutations_used = 0
        budget_hit = False
        step_summaries: list[dict[str, Any]] = []  # feeds the success-criteria verdict
        self._emit("plan_started", {"plan_id": plan.id, "goal_id": goal_id, "goal": plan.goal, "mode": mode.value})
        await queue.put({"type": "plan_started", "plan_id": plan.id, "status": "running"})
        self.episodes.append("plan", f"plan {plan.id} started for goal: {plan.goal}", session_id=session_id, goal_id=goal_id, plan_id=plan.id)

        failures = 0

        async def run_one(step: Step) -> tuple[bool, dict[str, Any]]:
            """Execute one approval-resolved step's tool call."""
            nonlocal mutations_used
            result = await self.registry.execute(step.tool, step.args)
            ok = result.get("status") == "ok"
            if ok and self.registry.is_mutating(step.tool):
                mutations_used += 1
            return ok, result

        i = 0
        while i < len(plan.steps):
            # ── guardrail budgets ──
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            if elapsed > self.budget_s:
                budget_hit = True
                for remaining in plan.steps[i:]:
                    if remaining.state == "pending":
                        remaining.state = "skipped"
                self.episodes.append(
                    "observation",
                    f"plan {plan.id} hit time budget ({int(elapsed)}s) — {len(plan.steps) - i} step(s) skipped",
                    session_id=session_id, goal_id=goal_id, plan_id=plan.id, status="budget",
                )
                break

            batch: list[Step] = []
            while i < len(plan.steps):
                step = plan.steps[i]
                mutates = self.registry.is_mutating(step.tool)
                if mutates and mutations_used >= self.max_mutations:
                    step.state = "skipped"
                    self.episodes.append(
                        "step",
                        f"step skipped ({step.tool}) — mutation budget exhausted ({self.max_mutations})",
                        session_id=session_id, goal_id=goal_id, plan_id=plan.id,
                        tool=step.tool, status="skipped",
                    )
                    i += 1
                    continue
                # mutating steps always run alone; reads batch up to 3
                if batch and (mutates or self.registry.is_mutating(batch[-1].tool)):
                    break
                batch.append(step)
                i += 1
                if len(batch) >= 3:
                    break

            gated: list[tuple[Step, Any]] = []
            for step in batch:
                mutates = self.registry.is_mutating(step.tool)
                decision = gate(self._modes.get(plan.id, mode), mutates)
                if decision == "wait_approval" and mode is not AutonomyMode.APPROVE and self.policy.trust(step.tool):
                    # earned autonomy: long success history on this exact tool
                    # buys it a pass under tiered mode (never under approve)
                    self.episodes.append(
                        "step",
                        f"{step.tool} auto-approved — earned autonomy (trusted tool history)",
                        session_id=session_id, goal_id=goal_id, plan_id=plan.id,
                        tool=step.tool, status="auto",
                    )
                    decision = "run"
                if decision == "wait_approval":
                    gated.append((step, None))
                else:
                    gated.append((step, True))

            # approvals must resolve before any of the batch runs
            approved_map: dict[int, bool] = {}
            for step, pre in gated:
                if pre is None:
                    approval = self.approvals.create(plan.id, step.index, step.tool, step.args, step.rationale)
                    step.state = "awaiting_approval"
                    self._emit("awaiting_approval", {"approval_id": approval["id"], "plan_id": plan.id, "step_index": step.index, "tool": step.tool, "args": step.args, "rationale": step.rationale})
                    await queue.put({"type": "awaiting_approval", "step_index": step.index, "approval_id": approval["id"], "tool": step.tool})
                    approved_map[id(step)] = await self.approvals.wait(approval["id"], self.timeout_s)

            for step, _pre in gated:
                if id(step) in approved_map and not approved_map[id(step)]:
                    step.state = "skipped"
                    reason = "rejected" if approved_map[id(step)] is False else "timed out"
                    self.episodes.append("step", f"step skipped ({step.tool}) — {reason}", session_id=session_id, goal_id=goal_id, plan_id=plan.id, tool=step.tool, status="skipped")
                    self.policy.observe(f"tool:{step.tool}", success=False)

            runnable = [(step, pre) for step, pre in gated if id(step) not in approved_map or approved_map[id(step)]]
            if not runnable:
                continue

            # read-only steps genuinely run concurrently; mutating ones are
            # alone in their batch by construction
            for step, _pre in runnable:
                step.state = "running"
                await queue.put({"type": "step_started", "step_index": step.index, "tool": step.tool})
            results = await asyncio.gather(*(run_one(step) for step, _pre in runnable))

            for (step, _pre), (ok, result) in zip(runnable, results):
                step.state = "done" if ok else "failed"
                if not ok:
                    failures += 1
                self.policy.observe(f"tool:{step.tool}", success=ok)
                summary_text = f"{step.tool} -> {'ok' if ok else 'error'}: {_brief(result)}"
                step_summaries.append({"tool": step.tool, "ok": ok, "brief": _brief(result)})
                episode = self.episodes.append(
                    "step", summary_text, session_id=session_id, goal_id=goal_id, plan_id=plan.id,
                    tool=step.tool, status="done" if ok else "failed",
                    result=result if ok else result.get("error"),
                )
                event = {"type": "step_finished", "step_index": step.index, "tool": step.tool, "ok": ok, "result": result, "episode_id": episode["id"]}
                self._emit("step_finished", {k: v for k, v in event.items() if k != "type"})
                await queue.put(event)

        # a plan fails only when everything that actually ran failed
        executed = [s for s in plan.steps if s.state in ("done", "failed")]
        plan.status = "failed" if executed and all(s.state == "failed" for s in executed) else "done"
        self.episodes.append(
            "observation",
            f"plan {plan.id} finished: status={plan.status}, failures={failures}, budget={budget_hit}",
            session_id=session_id, goal_id=goal_id, plan_id=plan.id, status=plan.status,
        )
        final = {
            "type": "plan_finished",
            "plan_id": plan.id,
            "status": plan.status,
            "failures": failures,
            "steps": len(plan.steps),
            "budget_hit": budget_hit,
        }
        self._emit("plan_finished", {k: v for k, v in final.items() if k != "type"})
        await queue.put(final)

        # ── success-criteria verdict (self-evaluation) ──
        criteria = getattr(plan, "verdict_criteria", "") or ""
        if criteria and self.judge is not None:
            try:
                transcript = json.dumps(step_summaries, default=str)[:3000]
                content = await self.judge.chat(
                    system='You grade whether an agent run met its stated success criteria. Respond exactly as {"verdict":"pass"|"fail","reasoning":"<one sentence>"}',
                    user=f"Goal: {plan.goal}\nSuccess criteria: {criteria}\nStep transcript:\n{transcript}",
                    json_mode=True,
                    num_predict=200,
                )
                match = re.search(r"\{.*\}", content, re.DOTALL)
                data = json.loads(match.group(0)) if match else {}
                verdict = str(data.get("verdict", "unknown"))
                reasoning = str(data.get("reasoning", ""))[:300]
            except Exception as exc:
                verdict, reasoning = "unknown", str(exc)[:200]
            self.episodes.append(
                "verdict",
                f"success-criteria verdict: {verdict} — {reasoning}",
                session_id=session_id, goal_id=goal_id, plan_id=plan.id,
                status="done" if verdict == "pass" else "failed",
                criteria=criteria[:300],
            )
            self._emit("verdict", {"plan_id": plan.id, "verdict": verdict, "reasoning": reasoning})

        self.active.pop(plan.id, None)


def _brief(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])[:120]
    payload = result.get("result")
    text = json.dumps(payload, default=str)
    return (text[:117] + "...") if len(text) > 120 else text
