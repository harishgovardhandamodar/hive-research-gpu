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
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from .autonomy import AutonomyMode, gate
from .events import EventBus
from .episodic import EpisodeStore
from .planner import Plan
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
    ) -> None:
        self.registry = registry
        self.episodes = episodes
        self.policy = policy
        self.bus = bus
        self.approvals = approvals
        self.timeout_s = approval_timeout_s
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
        self._emit("plan_started", {"plan_id": plan.id, "goal_id": goal_id, "goal": plan.goal, "mode": mode.value})
        await queue.put({"type": "plan_started", "plan_id": plan.id, "status": "running"})
        self.episodes.append("plan", f"plan {plan.id} started for goal: {plan.goal}", session_id=session_id, goal_id=goal_id, plan_id=plan.id)

        failures = 0
        for step in plan.steps:
            mutates = self.registry.is_mutating(step.tool)
            decision = gate(self._modes.get(plan.id, mode), mutates)
            if decision == "wait_approval":
                approval = self.approvals.create(plan.id, step.index, step.tool, step.args, step.rationale)
                step.state = "awaiting_approval"
                self._emit(
                    "awaiting_approval",
                    {
                        "approval_id": approval["id"],
                        "plan_id": plan.id,
                        "step_index": step.index,
                        "tool": step.tool,
                        "args": step.args,
                        "rationale": step.rationale,
                    },
                )
                await queue.put(
                    {
                        "type": "awaiting_approval",
                        "step_index": step.index,
                        "approval_id": approval["id"],
                        "tool": step.tool,
                    }
                )
                approved = await self.approvals.wait(approval["id"], self.timeout_s)
                if not approved:
                    step.state = "skipped"
                    self.episodes.append(
                        "step",
                        f"step skipped ({step.tool}) — {'rejected' if approved is False else 'timed out'}",
                        session_id=session_id,
                        goal_id=goal_id,
                        plan_id=plan.id,
                        tool=step.tool,
                        status="skipped",
                    )
                    self.policy.observe(f"tool:{step.tool}", success=False)
                    continue

            step.state = "running"
            await queue.put({"type": "step_started", "step_index": step.index, "tool": step.tool})
            result = await self.registry.execute(step.tool, step.args)
            ok = result.get("status") == "ok"
            step.state = "done" if ok else "failed"
            if not ok:
                failures += 1
            self.policy.observe(f"tool:{step.tool}", success=ok)
            summary = f"{step.tool} -> {'ok' if ok else 'error'}: {_brief(result)}"
            episode = self.episodes.append(
                "step",
                summary,
                session_id=session_id,
                goal_id=goal_id,
                plan_id=plan.id,
                tool=step.tool,
                status="done" if ok else "failed",
                result=result if ok else result.get("error"),
            )
            event = {
                "type": "step_finished",
                "step_index": step.index,
                "tool": step.tool,
                "ok": ok,
                "result": result,
                "episode_id": episode["id"],
            }
            self._emit("step_finished", {k: v for k, v in event.items() if k != "type"})
            await queue.put(event)

        plan.status = "failed" if failures and failures == len(plan.steps) else "done"
        self.episodes.append(
            "observation",
            f"plan {plan.id} finished: status={plan.status}, failures={failures}/{len(plan.steps)}",
            session_id=session_id,
            goal_id=goal_id,
            plan_id=plan.id,
            status=plan.status,
        )
        final = {
            "type": "plan_finished",
            "plan_id": plan.id,
            "status": plan.status,
            "failures": failures,
            "steps": len(plan.steps),
        }
        self._emit("plan_finished", {k: v for k, v in final.items() if k != "type"})
        await queue.put(final)
        self.active.pop(plan.id, None)


def _brief(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])[:120]
    payload = result.get("result")
    text = json.dumps(payload, default=str)
    return (text[:117] + "...") if len(text) > 120 else text
