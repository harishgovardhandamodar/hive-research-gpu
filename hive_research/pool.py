"""Research pool with local caching, import tracking, and similarity suggestions.

Monitors arXiv topics in the background, caches results locally with
both in-memory (LRU) and disk (SQLite) caches, tracks which papers get
imported to learn topic effectiveness, and suggests similar papers from
the pool when new papers are added to the knowledge graph.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from .arxiv_fetcher import search_arxiv
from .similarity import jaccard_tokens

logger = logging.getLogger(__name__)

CACHE_TTL = 12 * 3600
REFRESH_INTERVAL = 12 * 3600
MAX_PER_TOPIC = 100
SIMILARITY_THRESHOLD = 0.12
SUGGESTION_COUNT = 8

DEFAULT_TOPICS = [
    {"name": "Knowledge graphs", "query": "knowledge graph embedding"},
    {"name": "Federated learning", "query": "federated learning"},
    {"name": "AI security", "query": "AI security adversarial machine learning"},
    {"name": "LLM security", "query": "large language model security"},
    {"name": "AI alignment", "query": "AI alignment"},
    {"name": "Adversarial ML", "query": "adversarial machine learning"},
    {"name": "Graph neural networks", "query": "graph neural network"},
    {"name": "Vision-language models", "query": "vision language model"},
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    color TEXT NOT NULL DEFAULT '#60a5fa'
);

CREATE TABLE IF NOT EXISTS papers (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '[]',
    authors_str TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL DEFAULT '',
    abstract TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '[]',
    pdf_url TEXT NOT NULL DEFAULT '',
    topics TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    imported INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_papers_last_seen ON papers(last_seen);
CREATE INDEX IF NOT EXISTS idx_papers_imported ON papers(imported);

CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS similars (
    paper_a TEXT NOT NULL,
    paper_b TEXT NOT NULL,
    score REAL NOT NULL,
    updated TEXT NOT NULL,
    PRIMARY KEY (paper_a, paper_b)
);

CREATE INDEX IF NOT EXISTS idx_similars_a ON similars(paper_a);
CREATE INDEX IF NOT EXISTS idx_similars_score ON similars(score DESC);
"""

TOPIC_COLORS = [
    "#60a5fa", "#34d399", "#fbbf24", "#f87171",
    "#c084fc", "#22d3ee", "#fb923c", "#a78bfa",
]


class LRUCache:
    """Simple thread-safe LRU cache with optional TTL."""

    def __init__(self, maxsize: int = 128, ttl: float = 300) -> None:
        self._data: OrderedDict = OrderedDict()
        self._lock = Lock()
        self.maxsize = maxsize
        self.ttl = ttl

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._data:
                return None
            value, ts = self._data[key]
            if self.ttl > 0 and time.time() - ts > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (value, time.time())
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class ResearchPool:
    """Monitors arXiv topics with local caching, import-aware learning, and suggestions."""

    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

        import sqlite3
        self._db_path = str(self.store_dir / "pool.db")
        self._init_db()

        self._lock = Lock()
        self._mem_cache = LRUCache(maxsize=64, ttl=300)
        self._sim_cache: dict[str, list[dict[str, Any]]] = {}
        self._sim_cache_dirty = True

        if not self._has_topics():
            self._seed_default_topics()

        self._bg_thread = Thread(target=self._bg_loop, daemon=True)
        self._bg_thread.start()

    def _db_conn(self) -> Any:
        import sqlite3
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        import sqlite3
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.executescript(SCHEMA)
        # Migrations for schema changes
        try:
            conn.execute("SELECT color FROM topics LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE topics ADD COLUMN color TEXT NOT NULL DEFAULT '#60a5fa'")
            conn.commit()
        conn.commit()
        conn.close()

    def _has_topics(self) -> bool:
        conn = self._db_conn()
        row = conn.execute("SELECT COUNT(*) AS cnt FROM topics").fetchone()
        conn.close()
        return row["cnt"] > 0

    def _seed_default_topics(self) -> None:
        conn = self._db_conn()
        now = datetime.utcnow().isoformat()
        for i, t in enumerate(DEFAULT_TOPICS):
            color = TOPIC_COLORS[i % len(TOPIC_COLORS)]
            conn.execute(
                "INSERT OR IGNORE INTO topics (name, query, created_at, color) VALUES (?, ?, ?, ?)",
                (t["name"], t["query"], now, color),
            )
        conn.commit()
        conn.close()

    # ── Topic Management ──

    def get_topics(self) -> list[dict[str, Any]]:
        cached = self._mem_cache.get("topics")
        if cached:
            return cached
        conn = self._db_conn()
        rows = conn.execute("SELECT name, query, color FROM topics ORDER BY id").fetchall()
        conn.close()
        result = [dict(r) for r in rows]
        self._mem_cache.put("topics", result)
        return result

    def add_topic(self, name: str, query: str, **kwargs: Any) -> None:
        colors = TOPIC_COLORS
        conn = self._db_conn()
        existing = conn.execute("SELECT color FROM topics WHERE name = ?", (name,)).fetchone()
        color = existing["color"] if existing else colors[hash(name) % len(colors)]
        conn.execute("DELETE FROM topics WHERE name = ?", (name,))
        conn.execute(
            "INSERT INTO topics (name, query, color) VALUES (?, ?, ?)",
            (name, query, color),
        )
        conn.commit()
        conn.close()
        self._mem_cache.clear()

    def remove_topic(self, name: str) -> None:
        conn = self._db_conn()
        conn.execute("DELETE FROM topics WHERE name = ?", (name,))
        conn.commit()
        conn.close()
        self._mem_cache.clear()

    # ── Feed & Caching ──

    def get(self) -> dict[str, Any]:
        cached_feed = self._mem_cache.get("feed")
        if cached_feed:
            return cached_feed
        conn = self._db_conn()
        row = conn.execute(
            "SELECT value, timestamp FROM cache WHERE key = 'feed'"
        ).fetchone()
        conn.close()
        age = time.time() - row["timestamp"] if row else float("inf")
        data = json.loads(row["value"]) if row else {}
        if row and age < CACHE_TTL:
            self._mem_cache.put("feed", data)
        if age > CACHE_TTL:
            self._bg_refresh()
        return data

    def refresh(self) -> dict[str, Any]:
        return self._do_refresh()

    def _bg_refresh(self) -> None:
        Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self) -> dict[str, Any]:
        try:
            data = self._fetch_all()
            conn = self._db_conn()
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, timestamp) VALUES ('feed', ?, ?)",
                (json.dumps(data), time.time()),
            )
            conn.commit()
            conn.close()
            self._mem_cache.put("feed", data)
            self._rebuild_similarity_cache()
            return data
        except Exception as e:
            logger.error("Pool refresh failed: %s", e)
            conn = self._db_conn()
            row = conn.execute("SELECT value FROM cache WHERE key = 'feed'").fetchone()
            conn.close()
            return json.loads(row["value"]) if row else {}

    def _fetch_all(self) -> dict[str, Any]:
        topics = self.get_topics()
        result: dict[str, Any] = {}
        for i, topic in enumerate(topics):
            name = topic.get("name", "untitled")
            query = topic.get("query", "")
            if i > 0:
                time.sleep(3.5)
            try:
                papers = search_arxiv(query, max_results=MAX_PER_TOPIC)
                entries = []
                for p in papers:
                    entry = {
                        "arxiv_id": p.arxiv_id,
                        "title": p.title,
                        "authors": p.authors,
                        "authors_str": p.authors_str,
                        "published": p.published,
                        "abstract": p.abstract[:500],
                        "categories": p.categories,
                        "pdf_url": p.pdf_url,
                    }
                    entries.append(entry)
                    self._observe(entry, name)
                result[name] = entries
                logger.info("Pool topic '%s': %d papers", name, len(entries))
            except Exception as e:
                logger.warning("Pool topic '%s' fetch failed: %s", name, e)
                result[name] = []
        return result

    def _bg_loop(self) -> None:
        time.sleep(30)
        self._bg_refresh()
        while True:
            time.sleep(REFRESH_INTERVAL)
            self._bg_refresh()

    # ── Paper Observation ──

    def _observe(self, entry: dict[str, Any], topic: str) -> None:
        aid = entry["arxiv_id"]
        now = datetime.utcnow().isoformat()
        conn = self._db_conn()
        row = conn.execute(
            "SELECT topics, imported FROM papers WHERE arxiv_id = ?", (aid,)
        ).fetchone()
        if row:
            topics = json.loads(row["topics"])
            if topic not in topics:
                topics.append(topic)
            conn.execute(
                "UPDATE papers SET topics = ?, last_seen = ? WHERE arxiv_id = ?",
                (json.dumps(topics), now, aid),
            )
        else:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, authors, authors_str, "
                "published, abstract, categories, pdf_url, topics, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    entry.get("title", ""),
                    json.dumps(entry.get("authors", [])),
                    entry.get("authors_str", ""),
                    entry.get("published", ""),
                    entry.get("abstract", "")[:500],
                    json.dumps(entry.get("categories", [])),
                    entry.get("pdf_url", ""),
                    json.dumps([topic]),
                    now,
                    now,
                ),
            )
        conn.commit()
        conn.close()
        self._sim_cache_dirty = True

    # ── Similarity Cache ──

    def _rebuild_similarity_cache(self) -> None:
        """Pre-compute pairwise similarities for all pool papers and cache them."""
        papers = self.get_observed_papers()
        if len(papers) < 2:
            return
        conn = self._db_conn()
        conn.execute("DELETE FROM similars")
        inserted = 0
        for i in range(len(papers)):
            for j in range(i + 1, len(papers)):
                ta = (papers[i]["title"] or "") + " " + (papers[i]["abstract"] or "")
                tb = (papers[j]["title"] or "") + " " + (papers[j]["abstract"] or "")
                score = jaccard_tokens(ta, tb)
                if score >= SIMILARITY_THRESHOLD:
                    conn.execute(
                        "INSERT OR REPLACE INTO similars (paper_a, paper_b, score, updated) VALUES (?, ?, ?, ?)",
                        (papers[i]["arxiv_id"], papers[j]["arxiv_id"], round(score, 4),
                         datetime.utcnow().isoformat()),
                    )
                    inserted += 1
        conn.commit()
        conn.close()
        self._sim_cache.clear()
        self._sim_cache_dirty = False
        logger.info("Pool similarity cache: %d edges for %d papers", inserted, len(papers))

    def get_pool_graph(self) -> dict[str, Any]:
        """Return pool graph with similarity edges (uses cached similars)."""
        papers = self.get_observed_papers()
        nodes = []
        for p in papers:
            nodes.append({
                "id": p["arxiv_id"],
                "label": (p.get("title", "") or "")[:60],
                "type": "paper",
                "title": p.get("title", ""),
                "abstract": (p.get("abstract", "") or "")[:500],
                "arxiv_id": p["arxiv_id"],
                "authors": p.get("authors_str", ""),
                "published": p.get("published", ""),
                "imported": p.get("imported", False),
                "is_new": p.get("is_new", False),
                "topics": p.get("topics", []),
            })

        if self._sim_cache_dirty and len(papers) >= 2:
            Thread(target=self._rebuild_similarity_cache, daemon=True).start()

        conn = self._db_conn()
        rows = conn.execute(
            "SELECT paper_a, paper_b, score FROM similars ORDER BY score DESC LIMIT 2000"
        ).fetchall()
        conn.close()
        edges = [{"source": r["paper_a"], "target": r["paper_b"], "similarity": r["score"]} for r in rows]
        return {"nodes": nodes, "edges": edges}

    # ── Import Tracking & Insights ──

    def mark_imported(self, arxiv_id: str) -> None:
        conn = self._db_conn()
        conn.execute(
            "UPDATE papers SET imported = 1, imported_at = ? WHERE arxiv_id = ?",
            (datetime.utcnow().isoformat(), arxiv_id),
        )
        conn.commit()
        conn.close()

    def get_observed_papers(self) -> list[dict[str, Any]]:
        conn = self._db_conn()
        rows = conn.execute("SELECT * FROM papers ORDER BY last_seen DESC").fetchall()
        conn.close()
        now_ts = time.time()
        papers = []
        for r in rows:
            p = dict(r)
            p["authors"] = json.loads(p.get("authors", "[]"))
            p["categories"] = json.loads(p.get("categories", "[]"))
            p["topics"] = json.loads(p.get("topics", "[]"))
            p["tags"] = json.loads(p.get("tags", "[]"))
            p["imported"] = bool(p["imported"])
            fs = p.get("first_seen")
            try:
                p["is_new"] = fs and (now_ts - datetime.fromisoformat(fs).timestamp()) < 86400
            except Exception:
                p["is_new"] = False
            papers.append(p)
        return papers

    def update_tags(self, arxiv_id: str, tags: list[str]) -> None:
        conn = self._db_conn()
        conn.execute(
            "UPDATE papers SET tags = ? WHERE arxiv_id = ?",
            (json.dumps(tags), arxiv_id),
        )
        conn.commit()
        conn.close()

    def get_insights(self) -> dict[str, Any]:
        """Return topic-level performance and import statistics."""
        papers = self.get_observed_papers()
        total = len(papers)
        imported = sum(1 for p in papers if p["imported"])
        # Per-topic stats
        topic_stats: dict[str, dict[str, Any]] = {}
        for p in papers:
            for t in p.get("topics", []):
                if t not in topic_stats:
                    topic_stats[t] = {"observed": 0, "imported": 0, "papers": [], "imported_papers": []}
                topic_stats[t]["observed"] += 1
                topic_stats[t]["papers"].append(p["arxiv_id"])
                if p["imported"]:
                    topic_stats[t]["imported"] += 1
                    topic_stats[t]["imported_papers"].append(p["arxiv_id"])
        # Recent activity
        recent = [p for p in papers if p.get("is_new")]
        return {
            "total_papers": total,
            "imported_papers": imported,
            "conversion_rate": round(imported / max(total, 1), 3),
            "recent_new": len(recent),
            "topics": {
                name: {
                    "observed": s["observed"],
                    "imported": s["imported"],
                    "conversion_rate": round(s["imported"] / max(s["observed"], 1), 3),
                }
                for name, s in sorted(topic_stats.items(), key=lambda x: x[1]["observed"], reverse=True)
            },
        }

    # ── Suggestions ──

    def get_suggestions(self, paper_id: str, top_k: int = SUGGESTION_COUNT) -> list[dict[str, Any]]:
        """Find similar papers from the pool for a given paper ID.

        Returns top-K pool papers ranked by Jaccard similarity.
        """
        conn = self._db_conn()

        # First try cached similars from the pool graph
        rows = conn.execute(
            "SELECT paper_a, paper_b, score FROM similars WHERE paper_a = ? OR paper_b = ? "
            "ORDER BY score DESC LIMIT ?",
            (paper_id, paper_id, top_k),
        ).fetchall()

        if rows:
            conn.close()
            results = []
            seen = set()
            for r in rows:
                other = r["paper_b"] if r["paper_a"] == paper_id else r["paper_a"]
                if other in seen:
                    continue
                seen.add(other)
                results.append({"arxiv_id": other, "score": r["score"]})
            return results[:top_k]

        conn.close()

        # Fallback: find the paper in pool and compute on-the-fly
        pool_papers = self.get_observed_papers()
        target = None
        for p in pool_papers:
            if p["arxiv_id"] == paper_id:
                target = p
                break
        if not target:
            return []

        target_text = (target["title"] or "") + " " + (target["abstract"] or "")
        scored = []
        for p in pool_papers:
            if p["arxiv_id"] == paper_id:
                continue
            pt = (p["title"] or "") + " " + (p["abstract"] or "")
            score = jaccard_tokens(target_text, pt)
            if score >= SIMILARITY_THRESHOLD:
                scored.append({"arxiv_id": p["arxiv_id"], "score": round(score, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # ── Free-form Query ──

    def query_pool(self, query: str, max_local: int = 50, max_arxiv: int = 10) -> dict[str, Any]:
        """Free-form natural language query over pool papers with arXiv fallback.

        1. Extracts keywords from the query
        2. Searches local pool database (title, abstract, topics)
        3. Falls back to arXiv API for topics not found locally
        4. Returns matched papers + similarity graph
        """
        # Extract keywords (split on commas, remove common words)
        stop_words = {
            "find", "me", "a", "the", "that", "cover", "all", "for", "and",
            "or", "in", "on", "of", "to", "with", "about", "references",
            "papers", "research", "related", "including", "like", "such",
        }
        raw_keywords = re.split(r"[,;]", query)
        keywords = []
        for part in raw_keywords:
            for word in part.strip().lower().split():
                word = word.strip(".,!?\"'()[]")
                if word and len(word) > 2 and word not in stop_words:
                    keywords.append(word)
        keywords = list(set(keywords))
        if not keywords:
            return {"papers": [], "graph": []}

        # 1. Search local pool
        self._lock.acquire()
        try:
            rows = self._db_conn().execute(
                "SELECT * FROM papers ORDER BY last_seen DESC LIMIT ?",
                (1000,),
            ).fetchall()
        finally:
            self._lock.release()
        pool_papers = []
        for r in rows:
            p = dict(r)
            p["authors"] = json.loads(p.get("authors", "[]"))
            p["categories"] = json.loads(p.get("categories", "[]"))
            p["topics"] = json.loads(p.get("topics", "[]"))
            p["tags"] = json.loads(p.get("tags", "[]"))
            p["imported"] = bool(p["imported"])
            pool_papers.append(p)

        # Score each paper by keyword overlap
        scored_local = []
        for p in pool_papers:
            text = ((p.get("title", "") or "") + " " + (p.get("abstract", "") or "") + " " +
                    " ".join(p.get("topics", []))).lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored_local.append((p, score / len(keywords)))
        scored_local.sort(key=lambda x: x[1], reverse=True)
        matched_local = [p for p, s in scored_local[:max_local]]

        # 2. For keywords with no matches, fall back to arXiv
        matched_keywords = set()
        for p in matched_local:
            text = ((p.get("title", "") or "") + " " + (p.get("abstract", "") or "")).lower()
            for kw in keywords:
                if kw in text:
                    matched_keywords.add(kw)
        missing_keywords = [kw for kw in keywords if kw not in matched_keywords]

        # 3. Fetch from arXiv for missing keywords
        arxiv_papers = []
        seen_ids = {p["arxiv_id"] for p in matched_local}
        for kw in missing_keywords[:3]:  # Limit to 3 arXiv fallback queries
            try:
                results = search_arxiv(kw, max_results=max_arxiv)
                for r in results:
                    if r.arxiv_id not in seen_ids:
                        seen_ids.add(r.arxiv_id)
                        arxiv_papers.append({
                            "arxiv_id": r.arxiv_id,
                            "title": r.title,
                            "authors": r.authors,
                            "authors_str": r.authors_str,
                            "published": r.published,
                            "abstract": r.abstract[:500],
                            "categories": r.categories,
                            "pdf_url": r.pdf_url,
                            "topics": [f"query: {kw}"],
                            "imported": False,
                            "is_new": True,
                        })
                    time.sleep(3.5)  # Rate limit
            except Exception as e:
                logger.warning("arXiv fallback query '%s' failed: %s", kw, e)

        # 4. Build result
        all_papers = matched_local + arxiv_papers
        all_papers = all_papers[:max_local + max_arxiv]

        # Build similarity graph between result papers
        edges = []
        for i in range(len(all_papers)):
            for j in range(i + 1, len(all_papers)):
                ta = (all_papers[i]["title"] or "") + " " + (all_papers[i]["abstract"] or "")
                tb = (all_papers[j]["title"] or "") + " " + (all_papers[j]["abstract"] or "")
                score = jaccard_tokens(ta, tb)
                if score >= SIMILARITY_THRESHOLD:
                    edges.append({
                        "source": all_papers[i]["arxiv_id"],
                        "target": all_papers[j]["arxiv_id"],
                        "similarity": round(score, 4),
                    })

        # Format for frontend
        papers_out = []
        for p in all_papers:
            papers_out.append({
                "arxiv_id": p["arxiv_id"],
                "title": (p.get("title", "") or "")[:120],
                "authors_str": p.get("authors_str", ""),
                "published": p.get("published", ""),
                "abstract": (p.get("abstract", "") or "")[:500],
                "topics": p.get("topics", []),
                "imported": p.get("imported", False),
                "is_new": p.get("is_new", False),
            })

        return {"papers": papers_out, "graph": edges}
