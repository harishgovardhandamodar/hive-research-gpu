"""Python client for the Hive Research GPU API.

Provides a Pythonic interface to all REST endpoints without requiring
direct HTTP calls. Works with a running Hive server or directly against
an Organizer instance for embedded usage.

Usage:
    from hive_research import HiveClient

    # Remote (via REST API)
    client = HiveClient("http://localhost:7777")
    stats = client.stats()
    papers = client.papers()

    # Query with hybrid search
    answer = client.query("What is attention?", mode="hybrid")

    # Collections
    client.create_collection("my-papers")
    client.add_to_collection("my-papers", "1706.03762")

    # Export
    bibtex = client.export_bibtex()

    # Embedded (direct, no server required)
    from hive_research import Organizer, HiveClient
    org = Organizer(config)
    client = HiveClient(org=org)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HiveClient:
    """Python client for Hive Research GPU.

    Args:
        base_url: Base URL of a running Hive server (e.g. ``http://localhost:7777``).
        org: Direct Organizer instance for embedded usage (no server needed).
        auth_token: Optional Bearer token for authenticated servers.
    """

    def __init__(
        self,
        base_url: str | None = None,
        org: Any | None = None,
        auth_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.org = org
        self.auth_token = auth_token
        self._session: Any = None
        if self.base_url:
            import requests
            self._session = requests.Session()
            if auth_token:
                self._session.headers["Authorization"] = f"Bearer {auth_token}"

    def _assert_mode(self) -> None:
        if not self.base_url and not self.org:
            msg = "Provide base_url (remote) or org (embedded) to HiveClient"
            raise RuntimeError(msg)

    # ── HTTP helpers ──

    def _get(self, path: str) -> Any:
        if self.org:
            return self._direct_get(path)
        r = self._session.get(f"{self.base_url}{path}")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        if self.org:
            return self._direct_post(path, data or {})
        r = self._session.post(f"{self.base_url}{path}", json=data or {})
        r.raise_for_status()
        return r.json()

    def _direct_get(self, path: str) -> Any:
        """Route GET requests to Organizer directly."""
        path = path.rstrip("/")
        if path == "/api/stats":
            return self.org.stats()
        if path == "/api/graph":
            return self.org.graph_data()
        if path == "/api/papers":
            return self._papers_list()
        return {"error": "unsupported direct path", "path": path}

    def _direct_post(self, path: str, data: dict[str, Any]) -> Any:
        path = path.rstrip("/")
        if path == "/api/add":
            return self.org.add_by_id(data.get("id", ""), model=data.get("model"))
        if path == "/api/query":
            return self.org.query_rag(data.get("question", ""))
        return {"error": "unsupported direct path", "path": path}

    def _papers_list(self) -> list[dict[str, Any]]:
        from .pipeline import _sanitize_id
        papers = []
        for n in self.org.kg.papers:
            safe = _sanitize_id(n.label) or n.id
            note_path = Path(self.org.config.vault_dir) / safe / "00_notes.md"
            papers.append({
                "id": n.id, "title": n.label,
                "authors": (n.authors or ""),
                "published": n.published or "",
                "abstract": n.abstract or "",
            })
        return papers

    # ── System ──

    def stats(self) -> dict[str, Any]:
        """Get system statistics."""
        return self._get("/api/stats")

    def graph(self) -> dict[str, Any]:
        """Get knowledge graph in node-link format."""
        return self._get("/api/graph")

    def papers(self) -> list[dict[str, Any]]:
        """List all papers."""
        return self._get("/api/papers")

    def concepts(self) -> list[dict[str, Any]]:
        """List all concept nodes."""
        return self._get("/api/concepts")

    # ── Ingestion ──

    def add_paper(self, arxiv_id: str, model: str | None = None) -> dict[str, Any]:
        """Add a paper by arXiv ID."""
        return self._post("/api/add", {"id": arxiv_id, "model": model})

    def search_arxiv(self, query: str) -> list[dict[str, Any]]:
        """Search arXiv (no import)."""
        return self._post("/api/search", {"query": query})

    def import_papers(self, query: str, model: str | None = None) -> list[dict[str, Any]]:
        """Search arXiv and import all results."""
        return self._post("/api/import", {"query": query, "model": model})

    def ingest_web(self, url: str) -> dict[str, Any]:
        """Ingest a web URL as a graph node."""
        return self._post("/api/web/add", {"url": url})

    # ── RAG ──

    def query(
        self, question: str, mode: str = "hybrid"
    ) -> dict[str, Any]:
        """Ask a question using RAG.

        Args:
            question: Natural language question.
            mode: ``"vector"``, ``"keyword"``, or ``"hybrid"`` (default).

        Returns:
            Dict with ``answer`` and ``sources`` keys.
        """
        return self._post("/api/query", {"question": question, "mode": mode})

    def similarity(
        self,
        algorithm: str = "combined",
        paper_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Compute paper similarity matrix."""
        data: dict[str, Any] = {"algorithm": algorithm}
        if paper_ids:
            data["paper_ids"] = paper_ids
        if top_k:
            data["top_k"] = top_k
        return self._post("/api/similarity", data)

    # ── Collections ──

    def list_collections(self) -> dict[str, Any]:
        return self._get("/api/collections")

    def create_collection(self, name: str, description: str = "") -> dict[str, Any]:
        return self._post("/api/collections/create", {"name": name, "description": description})

    def delete_collection(self, name: str) -> dict[str, Any]:
        return self._post("/api/collections/delete", {"name": name})

    def add_to_collection(self, collection: str, paper_id: str) -> dict[str, Any]:
        return self._post("/api/collections/add", {"collection": collection, "paper_id": paper_id})

    def remove_from_collection(self, collection: str, paper_id: str) -> dict[str, Any]:
        return self._post("/api/collections/remove", {"collection": collection, "paper_id": paper_id})

    def get_collection_papers(self, collection: str) -> list[str]:
        return self._get(f"/api/collections/papers?collection={collection}")

    # ── Favorites ──

    def list_favorites(self) -> dict[str, Any]:
        return self._get("/api/favorites")

    def add_favorite(self, paper_id: str) -> dict[str, Any]:
        return self._post("/api/favorites/add", {"paper_id": paper_id})

    def remove_favorite(self, paper_id: str) -> dict[str, Any]:
        return self._post("/api/favorites/remove", {"paper_id": paper_id})

    # ── Saved Searches ──

    def list_saved_searches(self) -> list[dict[str, Any]]:
        return self._get("/api/searches")

    def save_search(self, query: str, name: str = "") -> dict[str, Any]:
        return self._post("/api/searches/save", {"query": query, "name": name})

    def delete_saved_search(self, index: int) -> dict[str, Any]:
        return self._post("/api/searches/delete", {"index": index})

    # ── Export ──

    def export_bibtex(self) -> str:
        """Export papers as BibTeX string."""
        if self.base_url:
            from urllib.parse import urljoin
            url = urljoin(self.base_url, "/api/export/bibtex")
            r = self._session.get(url)
            r.raise_for_status()
            return r.text
        if self.org:
            from .exporter import to_bibtex
            return to_bibtex(self.org.kg)
        return ""

    def export_json(self) -> str:
        """Export knowledge graph as JSON string."""
        if self.org:
            from .exporter import to_json_dump
            return to_json_dump(self.org.kg)
        return json.dumps(self._get("/api/export/json"), indent=2)

    def export_csv(self) -> str:
        """Export papers as CSV string."""
        if self.base_url:
            r = self._session.get(f"{self.base_url}/api/export/csv")
            r.raise_for_status()
            return r.text
        if self.org:
            from .exporter import papers_to_csv
            return papers_to_csv(self.org.kg)
        return ""

    def create_backup(self, output_path: str | None = None, include_pdfs: bool = False) -> bytes | str:
        """Create a backup ZIP. Returns bytes if using remote API."""
        if self.base_url:
            r = self._session.get(f"{self.base_url}/api/export/backup")
            r.raise_for_status()
            if output_path:
                Path(output_path).write_bytes(r.content)
            return r.content
        if self.org:
            from .exporter import create_backup as _backup
            return _backup(self.org.config, output_path=output_path, include_pdfs=include_pdfs)
        return b""
