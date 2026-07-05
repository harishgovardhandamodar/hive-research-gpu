# CLI Reference

## Usage

```bash
python -m hive_research [options] <command> [args]
```

## Global Options

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable debug-level logging |

## Commands

### `search`

Search arXiv without importing.

```bash
python -m hive_research search <query> [-n MAX_RESULTS]
```

Arguments:
- `query` — Search query string
- `-n`, `--max-results` — Number of results (default: 10)

Displays: arXiv ID, title, authors, published date, categories, first 200 chars of abstract.

### `add`

Add a paper by arXiv ID.

```bash
python -m hive_research add <arxiv_id> [--model MODEL]
```

Arguments:
- `id` — arXiv ID (e.g. `1706.03762`)
- `--model` — Model to use for analysis. `"large"` (default) uses the configured main model, `"fast"` uses the fast model, or pass any model name directly.

Triggers the full ingestion pipeline. Returns JSON with:
- `status`: `"added"`, `"exists"`, or `"error"`
- `paper_id`: arXiv ID
- `concepts`, `tags`, `relations`: count of extracted items
- `figures`: number of extracted figures
- `rag_chunks`: number of RAG chunks indexed
- `lineage`: cited papers linked (if any)
- `gpu_id`: GPU used for processing

### `import`

Search arXiv and import all results.

```bash
python -m hive_research import <query> [-n MAX_RESULTS] [--model MODEL]
```

Arguments:
- `query` — Search query
- `-n`, `--max-results` — Number of results (default: 10)
- `--model` — Model to use for analysis (same semantics as `add`).

Processes papers in parallel when multiple GPUs are available.

### `stats`

Show knowledge graph statistics.

```bash
python -m hive_research stats
```

Returns JSON with:
- `papers`, `concepts`, `relations` — Graph node/edge counts
- `rag.chunks`, `rag.dimension`, `rag.papers` — RAG index stats
- `gpu` — GPU status (if enabled)

### `similarity`

Compute pairwise paper similarity matrix.

```bash
python -m hive_research similarity
```

Displays top 10 most similar paper pairs with scores.

### `query`

Ask a RAG question over your paper library.

```bash
python -m hive_research query "<question>"
```

Returns an answer with source paper citations.

### `gpu`

Show GPU status.

```bash
python -m hive_research gpu
```

Returns JSON with device count, per-GPU memory, utilization, temperature, and power.

### `export`

Export papers or knowledge graph.

```bash
python -m hive_research export --bibtex papers.bib --json graph.json --csv papers.csv --backup backup.zip [--no-pdfs]
```

Options:
- `--bibtex [FILE]` — Export papers as BibTeX (default: `papers.bib`)
- `--json [FILE]` — Export graph JSON dump (default: `graph.json`)
- `--csv [FILE]` — Export papers as CSV (default: `papers.csv`)
- `--backup [FILE]` — Create ZIP backup (optional path)
- `--no-pdfs` — Exclude PDFs from backup

### `collections`

Manage paper collections, favorites, and saved searches.

```bash
python -m hive_research collections list
python -m hive_research collections create "my-papers" --description "..."
python -m hive_research collections delete "my-papers"
python -m hive_research collections add "my-papers" 1706.03762
python -m hive_research collections remove "my-papers" 1706.03762

python -m hive_research favorites list
python -m hive_research favorites add 1706.03762
python -m hive_research favorites remove 1706.03762
```

### `serve`

Start the web dashboard server.

```bash
python -m hive_research serve [--host HOST] [--port PORT]
```

Options:
- `--host` — Bind address (default: `127.0.0.1`)
- `--port` — Port (default: `7777`)
