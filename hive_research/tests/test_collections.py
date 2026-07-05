"""Tests for the paper collections module."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hive_research.collections import CollectionStore


class TestCollectionStore:
    def setup_method(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.path = self.tmp.name
        self.store = CollectionStore(self.path)

    def teardown_method(self) -> None:
        Path(self.path).unlink(missing_ok=True)

    # ── Collections ──

    def test_create_collection(self) -> None:
        r = self.store.create_collection("test-col")
        assert r["status"] == "created"
        cols = self.store.list_collections()
        assert "test-col" in cols

    def test_create_duplicate_collection(self) -> None:
        self.store.create_collection("dup")
        r = self.store.create_collection("dup")
        assert r["status"] == "exists"

    def test_delete_collection(self) -> None:
        self.store.create_collection("to-delete")
        r = self.store.delete_collection("to-delete")
        assert r["status"] == "deleted"
        assert "to-delete" not in self.store.list_collections()

    def test_delete_nonexistent(self) -> None:
        r = self.store.delete_collection("nope")
        assert r["status"] == "error"

    def test_add_paper_to_collection(self) -> None:
        self.store.create_collection("my-col")
        r = self.store.add_to_collection("my-col", "1706.03762")
        assert r["status"] == "added"
        papers = self.store.get_collection_papers("my-col")
        assert "1706.03762" in papers

    def test_add_duplicate_paper(self) -> None:
        self.store.create_collection("my-col")
        self.store.add_to_collection("my-col", "paper-1")
        r = self.store.add_to_collection("my-col", "paper-1")
        assert r["status"] == "added"  # idempotent

    def test_remove_paper_from_collection(self) -> None:
        self.store.create_collection("my-col")
        self.store.add_to_collection("my-col", "paper-1")
        r = self.store.remove_from_collection("my-col", "paper-1")
        assert r["status"] == "removed"
        assert "paper-1" not in self.store.get_collection_papers("my-col")

    def test_get_papers_from_nonexistent_collection(self) -> None:
        assert self.store.get_collection_papers("nope") == []

    def test_add_to_nonexistent_collection(self) -> None:
        r = self.store.add_to_collection("nope", "paper-1")
        assert r["status"] == "error"

    # ── Saved Searches ──

    def test_save_search(self) -> None:
        r = self.store.save_search("graph neural networks", name="GNN")
        assert r["status"] == "saved"
        searches = self.store.list_saved_searches()
        assert len(searches) == 1
        assert searches[0]["query"] == "graph neural networks"

    def test_delete_saved_search(self) -> None:
        self.store.save_search("query-1")
        self.store.save_search("query-2")
        r = self.store.delete_saved_search(0)
        assert r["status"] == "deleted"
        assert len(self.store.list_saved_searches()) == 1

    def test_delete_invalid_index(self) -> None:
        r = self.store.delete_saved_search(999)
        assert r["status"] == "error"

    # ── Favorites ──

    def test_add_favorite(self) -> None:
        r = self.store.add_favorite("1706.03762")
        assert r["status"] == "added"
        assert "1706.03762" in self.store.list_favorites()

    def test_add_duplicate_favorite(self) -> None:
        self.store.add_favorite("paper-1")
        r = self.store.add_favorite("paper-1")
        assert r["status"] == "exists"

    def test_remove_favorite(self) -> None:
        self.store.add_favorite("paper-1")
        r = self.store.remove_favorite("paper-1")
        assert r["status"] == "removed"
        assert "paper-1" not in self.store.list_favorites()

    def test_is_favorite(self) -> None:
        assert not self.store.is_favorite("paper-1")
        self.store.add_favorite("paper-1")
        assert self.store.is_favorite("paper-1")

    # ── Persistence ──

    def test_persistence(self) -> None:
        self.store.create_collection("persist-col")
        self.store.add_favorite("paper-42")
        self.store.save_search("test query")

        # Create new store instance reading same file
        store2 = CollectionStore(self.path)
        assert "persist-col" in store2.list_collections()
        assert "paper-42" in store2.list_favorites()
        assert len(store2.list_saved_searches()) == 1

    def test_empty_store(self) -> None:
        assert self.store.list_collections() == {}
        assert self.store.list_favorites() == []
        assert self.store.list_saved_searches() == []
