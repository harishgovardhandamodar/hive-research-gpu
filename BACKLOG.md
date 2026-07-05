# Hive Research GPU — Backlog

Prioritized, trackable improvements for the project.

---

## P0 — Critical (Current Sprint)

- [ ] **TEST** Add pytest infrastructure + core module tests (graph, similarity, RAG, pipeline)
- [ ] **PERF** Fix O(N²) similarity: cache results, top-K per paper, batch pagination
- [ ] **ARCH** Migrate `http.server` → FastAPI (async, WebSocket, auto-docs)
- [ ] **UI** Modularize dashboard JS into separate files (nav.js, graph.js, papers.js, chat.js)

## P1 — High Priority

- [ ] **FEAT** Add Jupyter notebooks (quick-start, KG analysis, RAG, API demo)
- [ ] **FEAT** Add Python client library (`HiveClient`)
- [ ] **FEAT** Export/import: BibTeX, JSON graph dump, full backup CLI + API
- [ ] **FEAT** Paper collections, saved searches, favorites
- [ ] **SEARCH** BM25 + hybrid search (vector + keyword) with RRF
- [ ] **UI** Graph improvements: minimap, expand-on-hover, path finder, timeline
- [ ] **QUALITY** Add Pydantic models for API schemas, config, data transfer
- [ ] **QUALITY** Extract shared dashboard UI into common CSS/JS modules

## P2 — Medium Priority

- [ ] **PERF** PDF extraction thread pool + text cache
- [ ] **PERF** Embedding caching with memory + disk tier
- [ ] **PERF** FAISS or hnswlib for ANN search
- [ ] **SECURITY** Optional basic auth + read-only mode
- [ ] **SECURITY** Input validation (arXiv IDs, URLs) + rate limiting
- [ ] **DEVOPS** CI/CD (GitHub Actions: lint, type-check, test, build)
- [ ] **DEVOPS** Multi-stage Docker build, health checks, non-root user
- [ ] **DEVOPS** Pre-commit hooks (ruff, mypy, prettier)

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
| — | — | — | — |
