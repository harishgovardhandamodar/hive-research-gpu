# Hive Research GPU

> Lightweight research knowledge base powered by dual NVIDIA RTX 5080 GPUs, local LLMs (Ollama via Hive Serving), and a Hive knowledge graph.

Hive Research GPU ingests academic papers from arXiv, extracts structured knowledge using local LLMs, builds a knowledge graph of concepts and citations, indexes content for RAG-based semantic search, and automatically monitors research topics — all running on consumer GPU hardware.

## Features

- **arXiv Ingestion** — Search, fetch metadata, download PDFs, extract text and figures
- **LLM-powered Analysis** — Extract summaries, concepts, tags, experiments, results, and relations using local Ollama models through a Hive Serving cluster (llama3.2, qwen3.6, nomic-embed-text)
- **Knowledge Graph** — Papers, concepts, tags, and web resources stored in a typed Hive graph with deduplication and similarity matching
- **RAG Search** — Chunk + embed pipeline with cosine similarity search; ask questions over your paper library
- **Research Pool** — Automatically monitor arXiv topics; observe new papers, batch-import into your knowledge base
- **Web Dashboard** — Real-time interactive dashboard with force-directed graph, browsing, similarity matrix, chat, and live logs
- **CLI** — Full command-line interface for search, import, stats, similarity, RAG queries, GPU monitoring, and export
- **Python Client Library** — `HiveClient` with remote (REST) and embedded modes for programmatic access
- **Hybrid Search** — BM25 keyword search fused with vector cosine similarity via Reciprocal Rank Fusion
- **Paper Collections** — Create collections, save searches, and favorite papers with CLI and API
- **Hive Serving** — Inference routed through the Hive Serving cluster (hive-server-go) for job queuing, load balancing, and GPU orchestration
- **Figure Extraction** — Extract figures, tables, and diagrams from PDFs with caption detection
- **Citation Lineage** — Automatically fetch and link cited papers, build citation graphs
- **Web Ingestion** — Add web articles/blog posts as graph nodes with LLM extraction
- **Docker** — Ready-to-deploy with `docker-compose` (NVIDIA GPU passthrough)

## Requirements

- Python 3.12+
- [Ollama](https://ollama.ai) with models pulled:
  - `llama3.2:3b` (fast tagging)
  - `qwen3.6:35b-mlx` or similar (main analysis)
  - `nomic-embed-text` (embeddings)
- [Hive Serving](https://github.com/hive-cluster/hive-serving) cluster running on port 8081 (or configured via `HIVE_BASE_URL`)
- NVIDIA GPU(s) with CUDA 12.4+ (optional, falls back to CPU)
- Internet access (arXiv API, PDF downloads)

## Installation

```bash
pip install hive-research-gpu
```

### From source

```bash
git clone https://github.com/your-org/hive-research-gpu
cd hive-research-gpu
pip install .
```

### Dependencies

Core dependencies are installed automatically: `arxiv`, `PyMuPDF`, `requests`, `PyYAML`, `numpy`, `pynvml`. Optional CUDA-accelerated dependencies (`cupy-cuda12x`) require `pip install .[cuda]`.

A separate dependency, `hive-datatype`, must be available on `PYTHONPATH` or installed alongside. It provides the `HiveGraph`, `Node`, and `Edge` data structures.

## Configuration

Copy and edit `config.yaml`:

```yaml
directories:
  root: ./data
  papers: ./data/papers
  graph: ./data/graph
  vault: ./data/vault

arxiv:
  download_pdf: true
  max_results: 10

hive:
  base_url: http://localhost:8081

ollama:
  base_url: http://localhost:11434
  model: qwen3.6:35b-mlx
  fast_model: llama3.2:3b
  embed_model: nomic-embed-text
  max_tokens: 16384
  temperature: 0.1

gpu:
  enabled: true
  device_count: 2
  parallel_papers: 2

graph:
  similarity_threshold: 0.85

rag:
  chunk_size: 512
  chunk_overlap: 64
  top_k: 5
```

Environment variables override settings: `HIVE_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_FAST_MODEL`, `OLLAMA_EMBED_MODEL`.

## Usage

### CLI

```bash
# Search arXiv
python -m hive_research search "transformer attention mechanism" -n 20

# Add a paper by arXiv ID
python -m hive_research add 1706.03762

# Search and import multiple papers
python -m hive_research import "graph neural networks" -n 5

# Show knowledge graph stats
python -m hive_research stats

# Compute paper similarity matrix
python -m hive_research similarity

# Ask a RAG question
python -m hive_research query "What architectures are used for graph classification?"

# Show GPU status
python -m hive_research gpu

# Start the web dashboard
python -m hive_research serve --host 0.0.0.0 --port 7777
```

### Web Dashboard

Start the server, then open `http://localhost:7777`:

```
python -m hive_research serve
```

The dashboard provides:
- **Pool** — Research pool observatory: browse papers discovered by topic monitors, import them into your graph
- **Graph** — Interactive force-directed knowledge graph with filtering, node preview, citation lineage
- **Import** — Add papers by arXiv ID/URL, ingest web articles, search and batch-import from arXiv
- **Browse** — Browse all papers, view vault notes, figures, experiment details, citation lineage
- **Similarity** — Pairwise similarity matrix (combined/abstract/author/concept algorithms)
- **Chat** — RAG question-answering over your paper library with source citations
- **About** — System stats, Ollama status, GPU monitoring

### Docker

```bash
docker-compose up --build
```

This launches the Hive Serving cluster (hive-server-go) and the web server with NVIDIA GPU passthrough. The Hive Server handles job queuing and load balancing for Ollama inference requests.

To build the Hive Server image separately:
```bash
cd ../hive-serving-local-Cluster
docker build -t hive-server-go -f hive-server-go/Dockerfile .
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Dashboard (HTML/JS)               │
│                      HTTP :7777                      │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                   Server (server.py)                 │
│         REST API — graph, stats, search, query       │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                    Organizer                         │
│          Orchestrates all subsystems                 │
├─────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐  │
│  │Pipeline  │ │Knowledge │ │   RAG    │ │ Pool  │  │
│  │(process) │ │  Graph   │ │ (search/ │ │(topic │  │
│  │          │ │ (hive-   │ │  answer) │ │observ)│  │
│  │          │ │ datatype)│ │          │ │       │  │
│  └────┬─────┘ └──────────┘ └────┬─────┘ └───────┘  │
│       │                         │                    │
│  ┌────┴─────────────────────────┴──────┐             │
│  │          LLMInterface                │             │
│  │   (Hive Server job API client)       │             │
│  └────────────────┬─────────────────────┘             │
│                   │                                  │
└───────────────────┼──────────────────────────────────┘
                    │
┌───────────────────┴──────────────────────────────────┐
│            Hive Server (hive-server-go :8081)          │
│   Job queue → load balancing → Ollama instance(s)     │
└──────────────────────────────────────────────────────┘
```

### Modules

| Module | Path | Description |
|--------|------|-------------|
| `arxiv_fetcher` | `hive_research/arxiv_fetcher.py` | arXiv API client: search, fetch by ID, download PDF |
| `parser` | `hive_research/parser.py` | PDF text/figure extraction via PyMuPDF |
| `llm` | `hive_research/llm.py` | Hive Server API client: generate, embed, structured extraction, parallel inference |
| `gpu` | `hive_research/gpu.py` | NVIDIA GPU monitoring (nvidia-smi) |
| `graph` | `hive_research/graph.py` | Knowledge graph wrapper around HiveGraph |
| `pipeline` | `hive_research/pipeline.py` | Paper ingestion pipeline: analysis, graph population, note writing |
| `rag` | `hive_research/rag.py` | RAG engine: chunking, embedding, cosine similarity, answer generation |
| `pool` | `hive_research/pool.py` | Research pool: SQLite-backed topic monitoring, arXiv scraping |
| `similarity` | `hive_research/similarity.py` | Paper similarity: author overlap, abstract Jaccard, concept overlap |
| `web_ingest` | `hive_research/web_ingest.py` | Web page ingestion: HTML extraction, LLM analysis, graph addition |
| `organizer` | `hive_research/organizer.py` | Top-level orchestrator: ties all subsystems together |
| `server` | `hive_research/server.py` | HTTP server (stdlib) with REST API + dashboard |
| `logs` | `hive_research/logs.py` | Captured log handler for in-memory log viewing |
| `config` | `hive_research/config.py` | YAML-based configuration with env var overrides |

## Research Pool

The Research Pool continuously monitors arXiv for topics of interest. It maintains a local SQLite database of observed papers and provides a UI for reviewing and selectively importing them into your knowledge graph.

Default topics:
- Knowledge graphs
- Federated learning
- AI security
- LLM security
- AI alignment
- Adversarial ML
- Graph neural networks
- Vision-language models

Topics refresh every 12 hours. New papers since the last observation are marked as "new".

## Similarity Algorithms

| Algorithm | Description |
|-----------|-------------|
| `combined` (default) | 40% author overlap + 40% abstract Jaccard + 20% edge overlap |
| `abstract` | Token Jaccard similarity over abstracts |
| `author` | Shared author ratio |
| `concept` | Overlap of shared knowledge graph concepts |

## Development

```bash
# Install in editable mode
pip install -e .

# Run benchmarks
python -m hive_research.tests.bench_ingestion --arxiv 2409.13004
```

## License

MIT
