# Architecture

## Overview

Hive Research GPU is organized as a layered system with three tiers:

1. **Interface Layer** — CLI (`__main__.py`) and REST API + SPA dashboard (`server.py`)
2. **Orchestration Layer** — `Organizer` ties together all subsystems
3. **Engine Layer** — Individual modules for arXiv, LLM, graph, RAG, pool, similarity

```
┌─────────────────────────────────────────────────────────────┐
│                     Interface Layer                          │
│  ┌────────────────────┐  ┌───────────────────────────────┐  │
│  │   CLI (argparse)   │  │  HTTP Server + SPA Dashboard  │  │
│  │  search/add/query   │  │  REST API :7777              │  │
│  │  import/serve/etc   │  │  Graph viz, browse, chat     │  │
│  └────────┬───────────┘  └──────────────┬────────────────┘  │
└───────────┼──────────────────────────────┼──────────────────┘
            │                              │
┌───────────┴──────────────────────────────┴──────────────────┐
│                   Orchestration Layer                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                     Organizer                         │   │
│  │  add_by_id()  add_by_search()  query_rag()           │   │
│  │  similarity()  stats()  refresh_papers()             │   │
│  │  fetch_lineage()  generate_definitions()             │   │
│  └───┬─────┬──────┬────────┬────────┬────────┬─────────┘   │
└──────┼─────┼──────┼────────┼────────┼────────┼─────────────┘
       │     │      │        │        │        │
┌──────┴┐ ┌──┴──┐ ┌─┴───┐ ┌──┴───┐ ┌──┴───┐ ┌─┴────┐
│Pipeline│ │  KG │ │ RAG │ │ Pool │ │ Web  │ │LLM   │
│process │ │graph│ │search│ │topic │ │Ingest│ │Inter.│
│_paper()│ │     │ │query │ │observ│ │      │ │      │
└───┬────┘ └─────┘ └──┬───┘ └──────┘ └──────┘ └──┬───┘
    │                  │                          │
┌───┴──────────────────┴──────────────────────────┴───┐
│                   GPUManager                         │
│  Ollama GPU 0 (port 11434)  Ollama GPU 1 (11435)    │
│  nvidia-smi monitoring, round-robin GPU assignment   │
└──────────────────────────────────────────────────────┘
```

## Data Flow: Paper Ingestion

```
arXiv ID/URL
    │
    ▼
1. arxiv_fetcher.fetch_by_id()
    • arXiv REST API → PaperInfo (title, authors, abstract, categories)
    │
    ▼
2. download_pdf()
    • HTTP GET https://arxiv.org/pdf/{id}.pdf → papers/{id}.pdf
    │
    ▼
3. parser.extract_text()
    • PyMuPDF → plain text
    │
    ▼
4. pipeline._analyze_text()
    • Tag extraction (fast LLM, GPU 0)
    • Concept/relation/summary/experiment extraction (main LLM, GPU 1)
    • JSON structure extraction with repair fallback
    │
    ▼
5. Knowledge Graph population
    • add_paper() → Node(type=PAPER)
    • add_concept() for each tag and extracted concept
    • add_edge() for relations, citations, concept links
    • Deduplication via fuzzy Jaccard matching (threshold 0.85)
    │
    ▼
6. Citation Lineage
    • Extract arXiv IDs from PDF references
    • Fetch metadata for each cited paper
    • Add as nodes with "cites" edges
    │
    ▼
7. Vault Notes
    • Markdown file with YAML frontmatter
    • Summary, notes, experiments, results, figures, concepts
    • Per-experiment markdown files
    │
    ▼
8. RAG Indexing
    • Chunk text (512 words, 64 overlap)
    • Parallel embedding across GPUs
    • Save to index.json + embeddings.npy
```

## Data Storage

| Location | Contents |
|----------|----------|
| `data/papers/{arxiv_id}.pdf` | Downloaded PDFs |
| `data/graph/main.json` | Knowledge graph (HiveGraph JSON) |
| `data/vault/{safe_title}/00_notes.md` | Paper notes with frontmatter |
| `data/vault/{safe_title}/{experiment}-00-experiment.md` | Per-experiment notes |
| `data/vault/{safe_title}/figures/` | Extracted figures |
| `data/rag/index.json` | RAG chunk index |
| `data/rag/embeddings.npy` | Dense embeddings (numpy) |
| `data/pool/pool.db` | Research pool SQLite database |

## Concurrency Model

- **GPU assignment** — Round-robin across available GPUs for LLM and embedding tasks
- **Parallel paper processing** — `threading.Thread` pool, one thread per paper, one GPU per thread
- **Embedding parallelism** — Chunk embeddings computed concurrently across GPUs
- **Server** — Single-threaded stdlib `HTTPServer`; background threads for pool refresh
