"""Pydantic models for API request/response validation.

Lightweight validation layer for the REST API.
Requires: pip install pydantic
"""

from __future__ import annotations

import re
from typing import Any
from datetime import date

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    # Fallback: plain dataclass if pydantic not installed
    from dataclasses import dataclass as BaseModel  # type: ignore

    def Field(*, default: Any = None, description: str = "") -> Any:  # type: ignore
        return default

    def field_validator(*args: Any, **kwargs: Any) -> Any:
        return lambda x: x


ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")


# ── Request Models ──


class AddPaperRequest(BaseModel):
    id: str = Field(..., description="arXiv ID (e.g. 1706.03762)")
    model: str | None = Field(None, description='Model: "large", "fast", or model name')

    @field_validator("id")
    @classmethod
    def validate_arxiv_id(cls, v: str) -> str:
        v = v.strip()
        if not ARXIV_ID_PATTERN.match(v):
            raise ValueError(f"Invalid arXiv ID format: {v}")
        return v


class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question")
    mode: str = Field("hybrid", description='Search mode: "vector", "keyword", "hybrid"')

    @field_validator("question")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question cannot be empty")
        return v.strip()


class SearchRequest(BaseModel):
    query: str = Field(..., description="arXiv search query")
    max_results: int = Field(10, ge=1, le=100, description="Max results")

    @field_validator("query")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class ImportRequest(BaseModel):
    query: str = Field(..., description="arXiv search query")
    max_results: int = Field(10, ge=1, le=50)
    model: str | None = None


class SimilarityRequest(BaseModel):
    paper_ids: list[str] | None = None
    algorithm: str = Field("combined", description="Algorithm name")
    top_k: int | None = Field(None, ge=1, le=1000)


class WebIngestRequest(BaseModel):
    url: str = Field(..., description="URL to ingest")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not URL_PATTERN.match(v):
            raise ValueError(f"Invalid URL format: {v}")
        return v


class CollectionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""


class CollectionPaperRequest(BaseModel):
    collection: str = Field(..., min_length=1)
    paper_id: str = Field(..., min_length=1)


class FavoriteRequest(BaseModel):
    paper_id: str = Field(..., min_length=1)


class SaveSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    name: str = ""


# ── Response Models ──


class PaperResponse(BaseModel):
    id: str
    title: str
    authors: str = ""
    published: str = ""
    abstract: str = ""
    affiliations: str = ""
    note_path: str = ""
    has_lineage: bool = False
    has_extra: bool = False


class StatsResponse(BaseModel):
    papers: int = 0
    concepts: int = 0
    relations: int = 0
    graph_papers: int = 0
    graph_refs: int = 0
    cross_edges: int = 0
    rag: dict[str, Any] = {}


class SimilarityResult(BaseModel):
    source: str
    source_title: str
    target: str
    target_title: str
    score: float
    author_overlap: float = 0.0
    abstract_sim: float = 0.0


class StatusResponse(BaseModel):
    status: str
    message: str = ""
