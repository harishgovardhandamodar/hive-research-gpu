# Hive Research GPU

> Lightweight research knowledge base powered by dual NVIDIA RTX 5080 GPUs, local LLMs (Ollama), and a Hive knowledge graph.

Hive Research GPU is a self-contained research assistant that ingests academic papers from arXiv, extracts structured knowledge using locally-run LLMs, builds a typed knowledge graph, and enables semantic search over your paper library — all running on consumer GPU hardware.

## Key Features

- **arXiv Ingestion** — Search, fetch metadata, download PDFs, extract text and figures via PyMuPDF
- **LLM-powered Analysis** — Extracts summaries, concepts, tags, experiments, results, and inter-paper relations using Ollama-hosted models (llama3.2, qwen3.6, nomic-embed-text)
- **Dual GPU Parallelism** — Two Ollama instances (one per GPU) for concurrent LLM inference and embedding
- **Knowledge Graph** — Papers, concepts, tags, and web resources stored as typed nodes in a Hive graph with deduplication and fuzzy concept matching
- **RAG Search** — Chunk → embed (parallel GPU) → cosine similarity → LLM answer generation with source citations
- **Research Pool** — Automatically monitors arXiv topics via a background scheduler; new papers are surfaced in the dashboard for selective import
- **Web Dashboard** — Real-time SPA with force-directed graph visualization, paper browsing, similarity matrix, RAG chat, and live activity logs
- **Web Ingestion** — Add blog posts and web articles as graph nodes with LLM-driven concept extraction
- **Citation Lineage** — Automatically detects cited arXiv IDs in PDFs, fetches metadata, and links them into the graph
- **Figure Extraction** — Extracts figures, tables, and diagrams from PDFs with heuristic caption detection; embeds them into vault notes
- **Docker** — Ready-to-deploy container setup with NVIDIA GPU passthrough and dual Ollama processes

## Quick Start

```bash
pip install hive-research-gpu

# Ensure Ollama is running with required models
ollama pull llama3.2:3b
ollama pull qwen3.6:35b-mlx
ollama pull nomic-embed-text

# Start the web dashboard
python -m hive_research serve
```

Open [http://localhost:7777](http://localhost:7777) and start adding papers.

## Project Structure

```
hive-research-gpu/
├── hive_research/
│   ├── __init__.py         # Package init, hive-datatype path setup
│   ├── __main__.py         # CLI entry point
│   ├── config.py           # YAML configuration reader
│   ├── arxiv_fetcher.py    # arXiv API client
│   ├── parser.py           # PDF text/figure extraction
│   ├── llm.py              # Ollama LLM interface
│   ├── gpu.py              # GPU monitoring and Ollama lifecycle
│   ├── graph.py            # Knowledge graph (HiveGraph wrapper)
│   ├── pipeline.py         # Paper ingestion pipeline
│   ├── rag.py              # RAG engine
│   ├── pool.py             # Research pool (topic monitoring)
│   ├── similarity.py       # Paper similarity algorithms
│   ├── web_ingest.py       # Web page ingestion
│   ├── organizer.py        # Top-level orchestrator
│   ├── server.py           # HTTP server + dashboard
│   ├── logs.py             # Captured log handler
│   ├── dashboard.html      # SPA dashboard
│   └── tests/
│       └── bench_ingestion.py  # Ingestion benchmark
├── config.yaml             # Default configuration
├── Dockerfile              # Container image
├── docker-compose.yml      # Deployment config
├── pyproject.toml           # Package metadata
└── README.md
```

## Dependencies

| Dependency | Purpose |
|-----------|---------|
| `arxiv` | arXiv API client (search, fetch) |
| `PyMuPDF` (fitz) | PDF text extraction and image extraction |
| `requests` | HTTP client for PDF download and Ollama API |
| `PyYAML` | Configuration file parsing |
| `numpy` | Embedding storage and cosine similarity |
| `pynvml` / `nvidia-ml-py3` | NVIDIA GPU monitoring |
| `hive-datatype` | Knowledge graph data structures (external) |
