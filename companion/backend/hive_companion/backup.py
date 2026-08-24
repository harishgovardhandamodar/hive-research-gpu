"""Durable storage helpers for agent data.

Every store already writes atomically (tmp + os.replace). This module adds
the second line of defence: rotating timestamped snapshots of all stores, so
accidental deletion/corruption of a live file can be rolled back, and safe
restoration that repairs runs interrupted mid-flight.
"""

from __future__ import annotations

import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

STORE_EXTS = {".jsonl", ".json"}
KEEP_SNAPSHOTS = 24


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def collect_store_files(data_dir: Path) -> list[Path]:
    if not data_dir.is_dir():
        return []
    return sorted(
        p for p in data_dir.iterdir()
        if p.is_file() and p.suffix.lower() in STORE_EXTS
    )


def create_snapshot(data_dir: Path, keep: int = KEEP_SNAPSHOTS, stamp: str | None = None) -> Path | None:
    """Snapshot all store files into data_dir/backups/<stamp>.tar.gz."""
    files = collect_store_files(data_dir)
    if not files:
        return None
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or utcnow().strftime("%Y%m%d_%H%M%S")
    arc = backup_dir / f"agentdata_{stamp}.tar.gz"
    with tarfile.open(arc, "w:gz") as tar:
        for f in files:
            tar.add(f, arcname=f.name)
    prune_snapshots(backup_dir, keep)
    return arc


def prune_snapshots(backup_dir: Path, keep: int = KEEP_SNAPSHOTS) -> list[Path]:
    snaps = sorted(backup_dir.glob("agentdata_*.tar.gz"))
    removed = []
    for old in snaps[:-keep] if len(snaps) > keep else []:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            continue
    return removed


def list_snapshots(data_dir: Path) -> list[dict[str, Any]]:
    backup_dir = data_dir / "backups"
    if not backup_dir.is_dir():
        return []
    out = []
    for arc in sorted(backup_dir.glob("agentdata_*.tar.gz"), reverse=True):
        stat = arc.stat()
        out.append({
            "file": arc.name,
            "bytes": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return out


T = TypeVar("T")


def load_runs(
    path: Path,
    factory: Callable[[dict[str, Any]], T],
    max_items: int = 10,
) -> list[T]:
    """Read persisted run dicts newest-last, repairing interrupted states."""
    runs: list[T] = []
    if not path.exists():
        return runs
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json_loads(line)
            except Exception:
                continue
            try:
                if data.get("status") == "running":
                    # a process died mid-run; it will never resume
                    data["status"] = "interrupted"
                runs.append(factory(data))
            except Exception:
                continue
    except OSError:
        return []
    return runs[-max_items:]


def json_loads(line: str) -> dict[str, Any]:
    import json

    result = json.loads(line)
    if not isinstance(result, dict):
        raise ValueError("not an object")
    return result


class BackupLoop:
    """Periodically snapshot stores; survives via start()/stop() pattern."""

    def __init__(self, data_dir: Path, interval_s: float = 21600.0, keep: int = KEEP_SNAPSHOTS) -> None:
        self.data_dir = data_dir
        self.interval_s = interval_s
        self.keep = keep
        self.last_snapshot: str | None = None
        self._task = None

    async def _loop(self) -> None:
        import asyncio

        while True:
            try:
                arc = create_snapshot(self.data_dir, keep=self.keep)
                if arc:
                    self.last_snapshot = arc.name
            except Exception:
                pass
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        import asyncio

        if self._task is None or self._task.done():
            # immediate first snapshot, then periodic
            try:
                arc = create_snapshot(self.data_dir, keep=self.keep)
                if arc:
                    self.last_snapshot = arc.name
            except Exception:
                pass
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        import asyncio

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
