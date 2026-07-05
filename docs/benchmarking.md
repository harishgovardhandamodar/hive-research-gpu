# Benchmarking

The project includes an end-to-end ingestion benchmark that measures per-stage latency for the full pipeline.

## Running

```bash
# Default benchmark (arXiv 2409.13004)
python -m hive_research.tests.bench_ingestion

# Custom paper
python -m hive_research.tests.bench_ingestion --arxiv 1706.03762

# From URL
python -m hive_research.tests.bench_ingestion --url https://arxiv.org/abs/2409.13004v1

# JSON output
python -m hive_research.tests.bench_ingestion --arxiv 2409.13004 --json

# Keep temp data for inspection
python -m hive_research.tests.bench_ingestion --arxiv 2409.13004 --keep-temp
```

## Measured Stages

| # | Stage | Description |
|---|-------|-------------|
| 1 | arXiv metadata fetch | `fetch_by_id()` via arXiv REST API |
| 2 | PDF download | HTTP download from arXiv |
| 3 | PDF text extraction | PyMuPDF text extraction |
| 4 | LLM tag extraction | Fast model → tags |
| 5 | LLM concept/relation extraction | Main model → concepts/relations/summary |
| 6 | Knowledge graph population | Node/edge creation + save |
| 7 | Note writing | Markdown vault file generation |
| 8 | RAG indexing | Chunk + parallel GPU embedding |
| 9 | RAG search | Query embed + cosine similarity |

## Sample Output

```
────────────────────────────────────────────────────────────
  Benchmarking ingestion of arXiv:2409.13004

────────────────────────────────────────────────────────────
  1. arXiv metadata fetch                         3.2 s
                                                     Title: OLMo: Accelerating the Science of L...
  2. PDF download                                  8.1 s
                                                     823 KB on disk
  3. PDF text extraction                           1.4 s
                                                     (98,432 chars, 14,221 words)
  4. LLM tag extraction (fast model)               2.1 s
                                                     (5 tags)
  5. LLM concept/relation extraction (main model)  18.7 s
                                                     (12 concepts, 4 relations)
  6. Knowledge graph population                    0.3 s
                                                     (graph: 1P/17C/13E)
  7. Note writing                                  0.1 s
                                                     (olmo_accelerating_the_science_of_language.md)
  8. RAG indexing (parallel GPU)                   5.2 s
                                                     (28 chunks, parallel GPU)
  9. RAG search (embed query + cosine)             0.4 s
                                                     (5 results)
────────────────────────────────────────────────────────────

  TOTAL                                           39.5 s
```

## Options

| Flag | Description |
|------|-------------|
| `--arxiv ID` | arXiv ID to benchmark |
| `--url URL` | arXiv URL to benchmark |
| `--keep-temp` | Preserve temp working directory |
| `--json` | Output timing data as JSON |
