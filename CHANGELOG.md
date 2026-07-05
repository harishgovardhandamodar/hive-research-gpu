# Changelog

## [0.3.0] — 2025-01-23

### Added
- **BM25 + Hybrid Search**: Keyword search with BM25 scoring, hybrid mode with Reciprocal Rank Fusion (vector + keyword)
- **Python Client Library**: `HiveClient` with remote (REST) and embedded (direct Organizer) modes, covering all API endpoints
- **Paper Collections**: Create/delete collections, add/remove papers, favorites, saved searches. CLI + REST API + `HiveClient`
- **Export/Import**: BibTeX, JSON graph dump, CSV, ZIP backup. CLI commands and API endpoints
- **Pydantic Schemas**: Validated request/response models with arXiv ID and URL format checking. Graceful fallback without pydantic
- **Auth**: Optional Bearer token authentication via `HIVE_AUTH_TOKEN` environment variable
- **Input Validation**: arXiv ID and URL validation on API endpoints
- **Jupyter Notebooks**: Quick-start, knowledge graph analysis (pandas/matplotlib), RAG demo with hybrid search
- **PDF Text Cache**: Disk + memory caching for extracted PDF text, thread pool for parallel extraction
- **CI/CD**: GitHub Actions workflow with lint (ruff), test (pytest), and build (python -m build)
- **`.dockerignore`**: Excludes dev artifacts from Docker builds

### Changed
- **Similarity Engine**: Pre-built edge/concept lookups reduce complexity from O(N² × E) to O(E + N²). Added `top_k` parameter
- **RAG Engine**: Refactored `search()` to support `mode` parameter (`vector`, `keyword`, `hybrid`). BM25 index auto-built from chunk texts
- **Dashboard**: Updated knowledge graph icon, removed redundant landscape page, improved sidebar navigation

### Fixed
- Landscape view crash caused by O(N² × E) similarity computation
- Tooltip forced layout thrash in landscape view
- `getComputedTextLength()` reflow storm in dashboard tick loop

### Removed
- Standalone `landscape.html` (replaced by embedded view in index.html)
- `/landscape` server route

## [0.2.0] — 2025-01-15

- Initial SPA dashboard with graph visualization, papers, similarity, RAG chat, import
- Dual GPU support with round-robin Ollama instances
- Research pool with automated arXiv topic monitoring
- Web ingestion for non-arXiv articles
- Citation lineage extraction from PDF references
- Figure extraction from PDFs
