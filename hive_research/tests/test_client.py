"""Tests for the HiveClient library using a mock server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hive_research import HiveClient


class TestHiveClientRemote:
    """Tests remote-mode HiveClient with mocked HTTP responses."""

    @pytest.fixture
    def client(self) -> HiveClient:
        return HiveClient(base_url="http://localhost:7777")

    def test_init_remote(self) -> None:
        c = HiveClient(base_url="http://localhost:7777")
        assert c.base_url == "http://localhost:7777"
        assert c.org is None

    def test_init_embedded(self) -> None:
        mock_org = MagicMock()
        c = HiveClient(org=mock_org)
        assert c.org is mock_org
        assert c.base_url is None

    def test_init_auth_token(self) -> None:
        c = HiveClient(base_url="http://localhost:7777", auth_token="secret123")
        assert c.auth_token == "secret123"
        assert "Authorization" in c._session.headers
        assert c._session.headers["Authorization"] == "Bearer secret123"

    def test_init_no_mode_raises(self) -> None:
        c = HiveClient()
        with pytest.raises(RuntimeError, match="Provide base_url"):
            c.stats()

    @patch("requests.Session.get")
    def test_stats(self, mock_get: MagicMock, client: HiveClient) -> None:
        mock_get.return_value.json.return_value = {"papers": 10, "concepts": 5}
        stats = client.stats()
        assert stats["papers"] == 10
        mock_get.assert_called_with("http://localhost:7777/api/stats")

    @patch("requests.Session.get")
    def test_graph(self, mock_get: MagicMock, client: HiveClient) -> None:
        mock_get.return_value.json.return_value = {"nodes": [], "links": []}
        graph = client.graph()
        assert "nodes" in graph

    @patch("requests.Session.get")
    def test_papers(self, mock_get: MagicMock, client: HiveClient) -> None:
        mock_get.return_value.json.return_value = [{"id": "test"}]
        papers = client.papers()
        assert len(papers) == 1

    @patch("requests.Session.post")
    def test_add_paper(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = {"status": "added"}
        result = client.add_paper("1706.03762")
        assert result["status"] == "added"
        mock_post.assert_called_with(
            "http://localhost:7777/api/add",
            json={"id": "1706.03762", "model": None},
        )

    @patch("requests.Session.post")
    def test_query(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = {"answer": "test", "sources": []}
        result = client.query("What is attention?")
        assert result["answer"] == "test"
        mock_post.assert_called_with(
            "http://localhost:7777/api/query",
            json={"question": "What is attention?", "mode": "hybrid"},
        )

    @patch("requests.Session.post")
    def test_create_collection(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = {"status": "created"}
        result = client.create_collection("my-col", "Test collection")
        assert result["status"] == "created"

    @patch("requests.Session.post")
    def test_add_to_collection(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = {"status": "added"}
        result = client.add_to_collection("my-col", "1706.03762")
        assert result["status"] == "added"

    @patch("requests.Session.post")
    def test_add_favorite(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = {"status": "added"}
        result = client.add_favorite("1706.03762")
        assert result["status"] == "added"

    @patch("requests.Session.post")
    def test_similarity(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = []
        result = client.similarity(algorithm="abstract")
        assert result == []

    @patch("requests.Session.post")
    def test_similarity_with_topk(self, mock_post: MagicMock, client: HiveClient) -> None:
        mock_post.return_value.json.return_value = []
        result = client.similarity(algorithm="combined", top_k=5)
        assert result == []

    @patch("requests.Session.get")
    def test_export_bibtex(self, mock_get: MagicMock, client: HiveClient) -> None:
        mock_get.return_value.text = "@misc{test}"
        result = client.export_bibtex()
        assert result == "@misc{test}"


class TestHiveClientEmbedded:
    """Tests embedded-mode HiveClient with a mock Organizer."""

    @pytest.fixture
    def mock_org(self) -> MagicMock:
        org = MagicMock()
        org.stats.return_value = {"papers": 3}
        org.graph_data.return_value = {"nodes": [], "links": []}
        org.add_by_id.return_value = {"status": "added"}
        org.query_rag.return_value = {"answer": "test answer", "sources": []}
        return org

    @pytest.fixture
    def client(self, mock_org: MagicMock) -> HiveClient:
        return HiveClient(org=mock_org)

    def test_stats_embedded(self, client: HiveClient) -> None:
        stats = client.stats()
        assert stats["papers"] == 3

    def test_graph_embedded(self, client: HiveClient) -> None:
        graph = client.graph()
        assert "nodes" in graph

    def test_add_paper_embedded(self, client: HiveClient) -> None:
        result = client.add_paper("1706.03762")
        assert result["status"] == "added"
