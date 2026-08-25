#!/usr/bin/env python3
"""Sync Fox Companion's fork cache from harishgovardhandamodar/ai-agent-papers.

Usage:
  python companion/scripts/sync_agents_from_fork.py                  # uses default FORK_URL → data/companion/agents_fork_cache.json
  python companion/scripts/sync_agents_from_fork.py --url URL         # custom fork/branch
  python companion/scripts/sync_agents_from_fork.py --check           # dry-run: just print counts

Also available live via the companion API:
  curl -X POST http://127.0.0.1:8001/api/agents/refresh
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# allow running as script without installing the package
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "companion" / "backend"))

from hive_companion.agents_fork import FORK_URL, fetch_and_cache, load_cached, parse_ai_scientist_md  # noqa: E402


def _fetch_sync(url: str) -> str:
    try:
        import httpx

        r = httpx.get(url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        import urllib.request

        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")


def main() -> None:
    p = argparse.ArgumentParser(description="Sync agents fork cache")
    p.add_argument("--url", default=FORK_URL, help="raw markdown URL for ai-scientist.md")
    p.add_argument("--data-dir", default="data/companion", help="companion data dir (where agents_fork_cache.json lives)")
    p.add_argument("--check", action="store_true", help="dry-run: fetch & parse, don't write")
    p.add_argument("--json", action="store_true", help="emit JSON summary")
    args = p.parse_args()

    try:
        md = _fetch_sync(args.url)
    except Exception as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        sys.exit(2)

    agents = parse_ai_scientist_md(md)
    by_cat: dict[str, int] = {}
    for a in agents:
        by_cat[a["category"]] = by_cat.get(a["category"], 0) + 1

    if args.check:
        summary = {"source": args.url, "count": len(agents), "by_category": by_cat}
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"source: {args.url}")
            print(f"total papers parsed: {len(agents)}")
            for cat, n in sorted(by_cat.items()):
                print(f"  {cat}: {n}")
        return

    data_dir = Path(args.data_dir)
    # reuse the same helper the backend uses so the cache file is byte-identical
    import asyncio

    result = asyncio.run(fetch_and_cache(data_dir, url=args.url))
    cached = load_cached(data_dir)
    if args.json:
        print(json.dumps({"source": result["source"], "count": result["count"], "cache_path": result["cache_path"], "by_category": by_cat}, indent=2))
    else:
        print(f"cached {result['count']} agents from {result['source']}")
        print(f"  → {result['cache_path']}")
        for cat, n in sorted(by_cat.items()):
            print(f"  {cat}: {n}")
        print(f"verify: load_cached -> {len(cached)} agents")


if __name__ == "__main__":
    main()
