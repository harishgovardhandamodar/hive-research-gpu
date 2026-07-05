# Contributing to Hive Research GPU

## Development Setup

```bash
git clone https://github.com/your-org/hive-research-gpu
cd hive-research-gpu

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[test]"
pip install ruff mypy pytest pytest-cov

# Ensure hive-datatype is available
git clone https://github.com/your-org/hive-datatype ../hive-datatype
```

## Code Style

- **Python**: Follow PEP 8. Run `ruff check` before committing.
- **JavaScript**: ES6 style, 2-space indent, no semicolons.
- **HTML**: 2-space indent, semantic elements.

## Testing

```bash
# Run all tests
python -m pytest hive_research/tests/ -v

# With coverage
python -m pytest hive_research/tests/ --cov=hive_research

# Run specific test file
python -m pytest hive_research/tests/test_similarity.py -v
```

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable, production-ready |
| `feat/*` | New features (branched from main) |
| `fix/*` | Bug fixes |
| `docs/*` | Documentation only |

Feature branches should be merged via PR with at least one review.

## Commit Messages

```
type: short description (max 72 chars)

Longer description with motivation and implementation notes.

Types: feat, fix, perf, test, docs, refactor, ci, chore
```

## Project Structure

```
hive_research/
├── __init__.py      # Package init, hive-datatype path setup
├── __main__.py      # CLI entry point
├── server.py        # HTTP server
├── client.py        # Python client library
├── organizer.py     # Top-level orchestrator
├── graph.py         # Knowledge graph
├── pipeline.py      # Paper ingestion pipeline
├── parser.py        # PDF text/figure extraction
├── rag.py           # RAG engine (vector + BM25 + hybrid)
├── llm.py           # Ollama LLM interface
├── gpu.py           # GPU monitoring
├── similarity.py    # Paper similarity algorithms
├── exporter.py      # Export/backup utilities
├── collections.py   # Paper collections, favorites, searches
├── schemas.py       # Pydantic validation models
├── pool.py          # Research pool
├── web_ingest.py    # Web page ingestion
├── arxiv_fetcher.py # arXiv API client
├── logs.py          # Log capture
├── config.py        # YAML configuration
├── dashboard.html   # Legacy dashboard SPA
├── index.html       # Main SPA dashboard
└── tests/           # pytest test files
```
