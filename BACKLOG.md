# Hive Research GPU — Backlog

Prioritized, trackable improvements for the project.

---

## P0 — Critical

- [x] **TEST** Add pytest infrastructure + core module tests (graph, similarity, RAG, pipeline)
- [x] **PERF** Fix O(N²) similarity: cache results, top-K per paper, batch pagination
- [ ] **ARCH** Migrate `http.server` → FastAPI (async, WebSocket, auto-docs)
- [ ] **UI** Modularize dashboard JS into separate files

## P1 — High Priority

- [x] **FEAT** Add Jupyter notebooks (quick-start, KG analysis, RAG, API demo)
- [x] **FEAT** Export/import: BibTeX, JSON graph dump, full backup CLI + API
- [x] **FEAT** Paper collections, saved searches, favorites
- [x] **SEARCH** BM25 + hybrid search (vector + keyword) with RRF
- [x] **QUALITY** Add Pydantic models for API schemas, config, data transfer
- [x] **SECURITY** Optional Bearer/token auth via `HIVE_AUTH_TOKEN`
- [x] **SECURITY** Input validation (arXiv IDs, URLs) with Pydantic schemas
- [x] **DEVOPS** CI/CD (GitHub Actions: lint, test, build)
- [ ] **FEAT** Add Python client library (`HiveClient`)
- [ ] **UI** Graph improvements: minimap, expand-on-hover, path finder, timeline

## P2 — Medium Priority

- [ ] **PERF** PDF extraction thread pool + text cache
- [ ] **PERF** Embedding caching with memory + disk tier
- [ ] **PERF** FAISS or hnswlib for ANN search
- [ ] **UI** Extract shared dashboard UI into common CSS/JS modules

## P3 — Nice to Have

- [ ] **FEAT** RAG query expansion (LLM generates alternative queries)
- [ ] **FEAT** RAG reranking with cross-encoder
- [ ] **FEAT** Graph layout switcher (circular, hierarchical, radial)
- [ ] **FEAT** Community detection (Louvain/Leiden) for graph coloring
- [ ] **FEAT** Dependency injection / context manager for shared state
- [ ] **FEAT** Backup scheduler (cron-based automatic backups)
- [ ] **FEAT** File-based logging with rotation
- [ ] **DOCS** Google-style docstrings on all public functions
- [ ] **DOCS** CONTRIBUTING.md, CHANGELOG.md, SECURITY.md
- [ ] **DOCS** Architecture diagram (not ASCII art — real diagram)

---

## Changelog

| Date | Item | Branch | Status |
|------|------|--------|--------|
| 2025-01-23 | P1: Fix O(N² × E) similarity with pre-built lookups + top_k | `feat/perf-similarity-cache` | ✅ Merged |
| 2025-01-23 | P0: pytest infra + conftest.py + test_similarity + test_graph | `feat/perf-similarity-cache` | ✅ Merged |
| 2025-01-23 | P1: Export/import (BibTeX, JSON, CSV, backup) + CLI + API + tests | `feat/export-import` | ✅ Done |
| 2025-01-23 | P0: Help page with rich docs, feature cards, Python/Jupyter tabs | `feat/help-page` | ✅ Merged |
| 2025-01-23 | P0: Remove landscape, deduplicate nav, fix graph icon | `feat/help-page` | ✅ Merged |
| 2025-01-23 | P1: Paper collections, favorites, saved searches + API + CLI + tests | `feat/develop` | ✅ Done |
| 2025-01-23 | P1: BM25 keyword search + hybrid RRF fusion in RAG engine | `feat/develop` | ✅ Done |
| 2025-01-23 | P2: Pydantic schemas with arXiv/URL validation, graceful fallback | `feat/develop` | ✅ Done |
| 2025-01-23 | P2: Optional Bearer/token auth via HIVE_AUTH_TOKEN | `feat/develop` | ✅ Done |
| 2025-01-23 | P1: Jupyter notebooks (quick-start, KG analysis, RAG demo) | `feat/develop` | ✅ Done |
| 2025-01-23 | P2: GitHub Actions CI (ruff lint, pytest, python build) | `feat/develop` | ✅ Done |
| 2025-01-23 | P2: .dockerignore, input validation for /api/add | `feat/develop` | ✅ Done |
