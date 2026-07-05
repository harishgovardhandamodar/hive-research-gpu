# Development

## Setup

```bash
git clone https://github.com/your-org/hive-research-gpu
cd hive-research-gpu

# Install in editable mode
pip install -e .

# Optional CUDA dependencies
pip install -e ".[cuda]"
```

## Project Layout

```
hive_research/
├── __init__.py         # Package init, hive-datatype autodiscovery
├── __main__.py         # CLI entry point
├── config.py           # Configuration
├── arxiv_fetcher.py    # arXiv API
├── parser.py           # PDF text/figure extraction
├── llm.py              # Ollama interface
├── gpu.py              # GPU management
├── graph.py            # Knowledge graph
├── pipeline.py         # Paper ingestion pipeline
├── rag.py              # RAG engine
├── pool.py             # Research pool
├── similarity.py       # Paper similarity
├── web_ingest.py       # Web ingestion
├── organizer.py        # Orchestrator
├── server.py           # HTTP server
├── logs.py             # Log capture
├── dashboard.html      # SPA dashboard
└── tests/
    └── bench_ingestion.py
```

## Testing

Run the end-to-end ingestion benchmark:

```bash
python -m hive_research.tests.bench_ingestion
python -m hive_research.tests.bench_ingestion --arxiv 2409.13004
python -m hive_research.tests.bench_ingestion --arxiv 2409.13004 --json
python -m hive_research.tests.bench_ingestion --arxiv 2409.13004 --keep-temp
```

The benchmark measures per-stage latency: arXiv fetch → PDF download → text extraction → LLM tagging → LLM concept extraction → graph population → note writing → RAG indexing → RAG search. Results are displayed as a timing table.

## Code Style

The project follows PEP 8 conventions with:
- Type hints throughout (`from __future__ import annotations`)
- Dataclasses for data models (`GPUDevice`)
- Property-based configuration access
- Explicit `threading.Lock` for thread safety
- Structured logging via `logging.getLogger(__name__)`

## Adding a New Similarity Algorithm

1. Add a scoring function to `similarity.py`
2. Register it in the `ALGORITHMS` dict with a lambda
3. The algorithm is automatically available via CLI, API, and dashboard

```python
def _new_score(kg, p1, p2, pid1, pid2) -> float:
    # Custom scoring logic
    return 0.5

ALGORITHMS["new_algo"] = {
    "label": "New Algorithm",
    "desc": "Description",
    "fn": lambda kg, p1, p2, pid1, pid2: _new_score(kg, p1, p2, pid1, pid2),
}
```

## Adding a New Command

1. Define a `cmd_*` function in `__main__.py`
2. Add a subparser with `sub.add_parser()`
3. Wire it up with `set_defaults(func=cmd_*)`

## Testing

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
python -m pytest hive_research/tests/ -v

# Run with coverage
python -m pytest hive_research/tests/ --cov=hive_research
```

The test suite uses mock fixtures from `tests/conftest.py`:

| File | Tests | What it covers |
|------|-------|----------------|
| `test_similarity.py` | 18 | All scoring functions and paper_similarity_matrix |
| `test_graph.py` | 11 | Mock graph operations |
| `test_exporter.py` | 13 | BibTeX, JSON, CSV, backup export |
| `test_collections.py` | 20 | Collections, favorites, saved searches |
| `test_rag.py` | 18 | BM25, vector/keyword/hybrid search |
| `test_client.py` | 20 | HiveClient remote + embedded modes |
| `test_faiss.py` | 2 | FAISS with numpy fallback |

## Frontend Development

The dashboard SPA is served at `/hive`. Static assets at `/static/`:

- `static/css/style.css` — All styles
- `static/js/nav.js` — Bootstrap helpers, theme, nav, dashboard, similarity, import
- `static/js/graph.js` — D3 force-directed graph
- `static/js/papers.js` — Paper list + detail overlay
- `static/js/chat.js` — RAG chat
- `static/js/help.js` — Help panel + init

No build step required — edit files and refresh the browser.

## Dependencies

The project depends on `hive-datatype` for graph data structures, which must be available on `PYTHONPATH`. The `__init__.py` attempts to auto-discover it at `../hive-datatype/` relative to the package.
