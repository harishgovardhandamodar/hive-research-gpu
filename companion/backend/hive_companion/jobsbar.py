"""Status-bar aggregation: one cheap snapshot of everything in flight."""

from __future__ import annotations

import re
from typing import Any

from .hive_client import HiveApiError, HiveClient


def extract_fox_job_ids(step_episodes: list[dict[str, Any]], limit: int = 4) -> list[str]:
    """Pull fox job ids (surveys etc.) out of recorded step results."""
    ids: list[str] = []
    seen = set()
    for ep in reversed(step_episodes):
        ctx = ep.get("context", {})
        if ctx.get("tool") not in ("survey.start",):
            continue
        result = ctx.get("result")
        jid = None
        if isinstance(result, dict):
            inner = result.get("result")
            if isinstance(inner, dict):
                jid = inner.get("job_id")
        elif isinstance(result, str):
            match = re.search(r'job_id"\s*:\s*"([0-9a-f]{6,})"', result)
            jid = match.group(1) if match else None
        if jid and jid not in seen:
            seen.add(jid)
            ids.append(jid)
            if len(ids) >= limit:
                break
    return ids


async def collect(
    client: HiveClient,
    plans_by_status: dict[str, int],
    approvals_pending: int,
    suggestions_open: int,
    fox_step_episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Best-effort snapshot; never raises — the bar must stay alive."""
    hive_ok = True
    hive_jobs: list[dict[str, Any]] = []
    try:
        data = await client.jobs()
        all_jobs = data.get("jobs", []) if isinstance(data, dict) else []
        hive_jobs = [
            {"label": j.get("label", j.get("kind", "?")), "status": j.get("status")}
            for j in all_jobs
            if j.get("status") in ("running", "pending")
        ][-5:]
    except HiveApiError:
        hive_ok = False

    fox_jobs: list[dict[str, Any]] = []
    # ids come back newest-first; poll only the few most recent
    for jid in extract_fox_job_ids(fox_step_episodes)[:3]:
        try:
            job = await client.get(f"/api/fox/job/{jid}")
            if job.get("status") in ("running", "queued"):
                fox_jobs.append(
                    {
                        "id": jid,
                        "status": job.get("status"),
                        "stage": job.get("stage", ""),
                        "progress": job.get("progress", 0),
                    }
                )
        except HiveApiError:
            continue

    return {
        "hive_ok": hive_ok,
        "plans_running": plans_by_status.get("running", 0),
        "approvals_pending": approvals_pending,
        "suggestions_open": suggestions_open,
        "hive_jobs": hive_jobs,
        "fox_jobs": fox_jobs,
    }
