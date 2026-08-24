"""Timeline assembly: episodes woven into per-goal threads for the GUI.

A thread starts at a `goal` episode; every episode whose goal_id matches is
filed under it (plans, steps, observations, feedback). Episodes without a
goal — conversations, suggestions — stay in `unfiled`, chronological.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .episodic import EpisodeStore


def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return datetime.min


def build_timeline(store: EpisodeStore, limit: int = 40) -> dict[str, Any]:
    episodes = store._load()
    threads: dict[str, dict[str, Any]] = {}
    unfiled: list[dict[str, Any]] = []

    for ep in episodes:
        goal_id = ep.get("goal_id") or ""
        if not goal_id and ep["kind"] == "goal":
            goal_id = ep["id"]
        if not goal_id:
            unfiled.append(ep)
            continue
        thread = threads.get(goal_id)
        if thread is None:
            if ep["kind"] == "goal":
                thread = {"goal": ep}
            else:
                # orphaned step/plan from before its goal episode (or across
                # restarts): synthesize a lightweight thread header
                thread = {"goal": {"id": goal_id, "ts": ep["ts"], "summary": f"(goal {goal_id})", "kind": "goal"}}
            threads[goal_id] = thread

    for ep in episodes:
        goal_id = ep.get("goal_id") or ""
        if not goal_id and ep["kind"] == "goal":
            continue  # already owns its thread
        if not goal_id:
            continue
        thread = threads[goal_id]
        kind = ep["kind"]
        if kind == "step":
            ctx = ep.get("context", {})
            thread.setdefault("steps", []).append(
                {
                    "ts": ep["ts"],
                    "tool": ctx.get("tool", "?"),
                    "status": ctx.get("status", "done"),
                    "summary": ep["summary"],
                }
            )
        elif kind == "feedback":
            thread.setdefault("decisions", []).append({"ts": ep["ts"], "summary": ep["summary"]})
        elif kind == "plan":
            thread.setdefault("plans", []).append(
                {"ts": ep["ts"], "plan_id": ep.get("context", {}).get("plan_id"), "summary": ep["summary"]}
            )
        elif kind == "observation":
            thread.setdefault("observations", []).append({"ts": ep["ts"], "summary": ep["summary"]})
        else:
            thread.setdefault("events", []).append({"ts": ep["ts"], "kind": kind, "summary": ep["summary"]})

    out = []
    for goal_id, thread in threads.items():
        steps = sorted(thread.get("steps", []), key=lambda s: s["ts"])
        events = (
            thread.get("plans", [])
            + thread.get("decisions", [])
            + thread.get("observations", [])
            + thread.get("events", [])
        )
        all_ts = [ep["ts"] for ep in ([thread["goal"]] + steps + events) if ep.get("ts")]
        status = "unknown"
        observations = sorted(thread.get("observations", []), key=lambda o: o["ts"])
        if observations:
            last = observations[-1]["summary"]
            if "status=done" in last:
                status = "done"
            elif "status=failed" in last:
                status = "failed"
        elif steps:
            status = "running"
        failed = sum(1 for s in steps if s["status"] == "failed")
        skipped = sum(1 for s in steps if s["status"] == "skipped")
        span_s = 0
        if len(all_ts) >= 2:
            span_s = int((_parse(max(all_ts)) - _parse(min(all_ts))).total_seconds())
        out.append(
            {
                "goal_id": goal_id,
                "goal": thread["goal"].get("summary", ""),
                "started": min(all_ts) if all_ts else "",
                "last": max(all_ts) if all_ts else "",
                "span_s": span_s,
                "status": status,
                "steps": steps,
                "steps_ok": sum(1 for s in steps if s["status"] == "done"),
                "steps_failed": failed,
                "steps_skipped": skipped,
                "decisions": sorted(thread.get("decisions", []), key=lambda d: d["ts"]),
                "events": sorted(events, key=lambda e: e["ts"]),
            }
        )

    out.sort(key=lambda t: t["started"], reverse=True)
    return {
        "threads": out[:limit],
        "unfiled": [
            {"ts": e["ts"], "kind": e["kind"], "summary": e["summary"]} for e in sorted(unfiled, key=lambda x: x["ts"])[-limit:]
        ],
        "total_threads": len(out),
    }
