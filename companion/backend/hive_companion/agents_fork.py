"""Live sync from the user's fork — parses ai-scientist.md into agent dicts.

FORK_URL points to harishgovardhandamodar/ai-agent-papers so any edit
there can be pulled into Fox Companion via POST /api/agents/refresh
or the companion/scripts/sync_agents_from_fork.py helper.

Cache lives at <data_dir>/agents_fork_cache.json so the companion works
offline after the first fetch.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

FORK_URL = "https://raw.githubusercontent.com/harishgovardhandamodar/ai-agent-papers/main/applications/domain/ai-scientist.md"

# map markdown section headings → catalog category
SECTION_TO_CAT = {
    "Idea Generation & Hypothesis": "ideation",
    "Idea Generation": "ideation",
    "Experimentation & Discovery": "experimentation",
    "Experimentation": "experimentation",
    "Paper Writing & Peer Review": "writing",
    "Paper Writing": "writing",
}

# colors per category (match agents_catalog.py)
CAT_COLOR = {"ideation": "#f0b429", "experimentation": "#3fb27f", "writing": "#7fb4d4"}
CAT_ICON = {"ideation": "💡", "experimentation": "🔬", "writing": "📝"}

# capture: [Mon YYYY] **"Title"** [[paper](URL)]  (emoji/📖/⚖️/🔥 prefixes tolerated)
BULLET_RE = re.compile(
    r'^\*\s+\[[^\]]+\]\s+.*?\"(?P<title>[^\"]+)\"[^\[]*\[\[paper\]\((?P<url>[^)]+)\)',
    re.MULTILINE,
)
ARXIV_RE = re.compile(r"arxiv\.org/abs/([0-9.]+)", re.I)
# fallback: any quoted title in a bullet
FALLBACK_TITLE_RE = re.compile(r'"([^"]{6,})"')
SECTION_RE = re.compile(r"^###\s+(?P<sec>.+?)\s*$", re.MULTILINE)


def _slug(title: str, arxiv: str | None) -> str:
    if arxiv:
        return arxiv.replace(".", "-").replace("/", "-")
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "agent"


def _category_for_section(sec: str) -> str | None:
    sec = sec.strip()
    for k, cat in SECTION_TO_CAT.items():
        if k.lower() in sec.lower():
            return cat
    return None


def parse_ai_scientist_md(md: str) -> list[dict[str, Any]]:
    """Parse raw markdown into a list of agent-like dicts (all papers).

    Each dict has: id, name, category, paper_title, paper_url, arxiv_id,
    date, section.
    """
    # split by sections so every bullet knows its category
    sections: list[tuple[str, int, int]] = []  # (sec_title, start, end)
    headings = [(m.group("sec"), m.start()) for m in SECTION_RE.finditer(md)]
    headings.append(("", len(md)))
    for i in range(len(headings) - 1):
        sec, start = headings[i]
        _, nxt = headings[i + 1]
        sections.append((sec, start, nxt))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sec, a, b in sections:
        cat = _category_for_section(sec)
        if cat is None:
            continue
        chunk = md[a:b]
        for m in BULLET_RE.finditer(chunk):
            title = m.group("title").strip()
            url = m.group("url").strip()
            # try to extract date prefix "[Apr 2024]" from the bullet
            date_m = re.search(r"\[([A-Za-z]{3}\s+\d{4})\]", m.group(0))
            date = date_m.group(1) if date_m else ""
            arxiv = None
            am = ARXIV_RE.search(url)
            if am:
                arxiv = am.group(1)
            sid = _slug(title, arxiv)
            if sid in seen:
                continue
            seen.add(sid)
            # short name = first 2-3 words of title, trimmed
            short = title.split(":")[0].split("—")[0].strip()
            if len(short) > 38:
                short = short[:38].rstrip() + "…"
            out.append(
                {
                    "id": sid,
                    "name": short,
                    "category": cat,
                    "section": sec.strip(),
                    "paper_title": title,
                    "paper_url": url,
                    "arxiv_id": arxiv,
                    "date": date,
                    "tagline": title[:90],
                    "description": title,
                    "icon": CAT_ICON.get(cat, "🤖"),
                    "color": CAT_COLOR.get(cat, "#8b96a8"),
                    "from_fork": True,
                }
            )
    return out


def _cache_path(data_dir: str | Path | None) -> Path:
    if data_dir is None:
        return Path("data/companion/agents_fork_cache.json")
    p = Path(data_dir)
    if p.suffix == ".json":
        return p
    return p / "agents_fork_cache.json"


def load_cached(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    path = _cache_path(data_dir)
    if not path.is_file():
        # also try sibling of agent_selection.json
        alt = path.parent / "agents_fork_cache.json"
        if alt.is_file():
            path = alt
        else:
            return []
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and "agents" in raw:
            return raw["agents"]
        if isinstance(raw, list):
            return raw
    except Exception:
        return []
    return []


def save_cache(agents: list[dict[str, Any]], data_dir: str | Path | None, source_url: str = FORK_URL) -> Path:
    path = _cache_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": source_url, "fetched_at": time.time(), "count": len(agents), "agents": agents}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
    return path


async def fetch_and_cache(data_dir: str | Path | None = None, url: str = FORK_URL) -> dict[str, Any]:
    """Fetch markdown from fork, parse, cache, and return summary.

    Uses httpx if available, falls back to urllib. Called from FastAPI
    (async) — the HTTP fetch is done in a thread to avoid blocking.
    """
    import asyncio

    def _fetch_sync() -> str:
        # prefer httpx (already a dependency via hive_client), fallback to urllib
        try:
            import httpx  # type: ignore

            resp = httpx.get(url, timeout=20, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception:
            import urllib.request

            with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310
                return r.read().decode("utf-8", errors="replace")

    md = await asyncio.to_thread(_fetch_sync)
    agents = parse_ai_scientist_md(md)
    path = save_cache(agents, data_dir, source_url=url)
    return {"fetched_at": time.time(), "count": len(agents), "agents": agents, "cache_path": str(path), "source": url}
