"""Paper collections, saved searches, and favorites.

Provides persistent user-defined collections of papers stored as JSON.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class CollectionStore:
    """Persistent store for user-defined paper collections and saved searches.

    Data is stored as a JSON file at ``<root_dir>/collections.json``.
    Thread-safe via a reentrant lock.
    """

    def __init__(self, store_path: str | Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception as e:
                logger.warning("Failed to load collections: %s", e)
        return {"collections": {}, "saved_searches": [], "favorites": []}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2, default=str))

    # ── Collections ──

    def list_collections(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._data.get("collections", {}))

    def create_collection(self, name: str, description: str = "") -> dict[str, Any]:
        with self._lock:
            collections = self._data.setdefault("collections", {})
            if name in collections:
                return {"status": "exists", "collection": name}
            collections[name] = {
                "name": name,
                "description": description,
                "papers": [],
                "created": datetime.now().isoformat(),
                "updated": datetime.now().isoformat(),
            }
            self._save()
            logger.info("Created collection: %s", name)
            return {"status": "created", "collection": name}

    def delete_collection(self, name: str) -> dict[str, Any]:
        with self._lock:
            collections = self._data.get("collections", {})
            if name not in collections:
                return {"status": "error", "message": f"Collection '{name}' not found"}
            del collections[name]
            self._save()
            logger.info("Deleted collection: %s", name)
            return {"status": "deleted", "collection": name}

    def add_to_collection(self, collection: str, paper_id: str) -> dict[str, Any]:
        with self._lock:
            collections = self._data.get("collections", {})
            if collection not in collections:
                return {"status": "error", "message": f"Collection '{collection}' not found"}
            papers = collections[collection].setdefault("papers", [])
            if paper_id not in papers:
                papers.append(paper_id)
                collections[collection]["updated"] = datetime.now().isoformat()
                self._save()
            return {"status": "added", "collection": collection, "paper_id": paper_id}

    def remove_from_collection(self, collection: str, paper_id: str) -> dict[str, Any]:
        with self._lock:
            collections = self._data.get("collections", {})
            if collection not in collections:
                return {"status": "error", "message": f"Collection '{collection}' not found"}
            papers = collections[collection].get("papers", [])
            if paper_id in papers:
                papers.remove(paper_id)
                collections[collection]["updated"] = datetime.now().isoformat()
                self._save()
            return {"status": "removed", "collection": collection, "paper_id": paper_id}

    def get_collection_papers(self, collection: str) -> list[str]:
        with self._lock:
            return list(self._data.get("collections", {}).get(collection, {}).get("papers", []))

    # ── Saved Searches ──

    def list_saved_searches(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._data.get("saved_searches", []))

    def save_search(self, query: str, name: str = "") -> dict[str, Any]:
        with self._lock:
            searches = self._data.setdefault("saved_searches", [])
            entry = {
                "name": name or query[:60],
                "query": query,
                "created": datetime.now().isoformat(),
            }
            searches.append(entry)
            self._save()
            return {"status": "saved", "search": entry}

    def delete_saved_search(self, index: int) -> dict[str, Any]:
        with self._lock:
            searches = self._data.get("saved_searches", [])
            if 0 <= index < len(searches):
                removed = searches.pop(index)
                self._save()
                return {"status": "deleted", "search": removed}
            return {"status": "error", "message": "Invalid search index"}

    # ── Favorites ──

    def list_favorites(self) -> list[str]:
        with self._lock:
            return list(self._data.get("favorites", []))

    def add_favorite(self, paper_id: str) -> dict[str, Any]:
        with self._lock:
            favs = self._data.setdefault("favorites", [])
            if paper_id not in favs:
                favs.append(paper_id)
                self._save()
                return {"status": "added", "paper_id": paper_id}
            return {"status": "exists", "paper_id": paper_id}

    def remove_favorite(self, paper_id: str) -> dict[str, Any]:
        with self._lock:
            favs = self._data.get("favorites", [])
            if paper_id in favs:
                favs.remove(paper_id)
                self._save()
            return {"status": "removed", "paper_id": paper_id}

    def is_favorite(self, paper_id: str) -> bool:
        with self._lock:
            return paper_id in self._data.get("favorites", [])
