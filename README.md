# Hive Research GPU

> Lightweight research knowledge base powered by local LLMs (Ollama), a Hive knowledge graph, and **Fox** — your local research companion.

Hive Research GPU ingests academic papers from arXiv, extracts structured knowledge using local LLMs, builds a knowledge graph of concepts and citations, indexes content for RAG-based semantic search, monitors research topics — and serves it all through **Fox**, a grounded local chatbot with six reasoning modes. It is designed as an ideal companion for following arXiv work in AI agents, alignment & safety, multi-agent systems, agent swarms, and LLM security.

## Features

- **Fox Research Companion** — six modes: `Fast` · `RAG` · `Thinking` · `Deep-Thinking` · `Deep Research` · `Survey Report`. Every corpus-grounded answer carries `[n]` citations back to your papers
  - *Thinking* exposes an inspectable reasoning trace; *Deep-Thinking* decomposes questions into sub-questions; *Deep Research* runs plan → retrieve → gap-check loops; *Survey Report* writes a full markdown survey into your vault
  - Three view modes: full panel, resizable half-panel (`Ctrl/Cmd+K`), and draggable/resizable floating window
  - Rate answers 👍/👎 — ratings feed the reinforcement loop
- **Reinforcement Loop** — low-rated notes are re-analyzed automatically with your criticism injected as improvement hints; Fox continuously learns from past feedback
- **arXiv Ingestion** — Search, fetch metadata, download PDFs, extract text and figures; live per-stage job tracking (fetch → pdf → parse → analyze → graph → notes → rag → lineage)
- **Domain Presets** — curated topic packs for LLM agents, multi-agent systems, swarms, alignment, LLM security, agentic security
- **LLM-powered Analysis** — summaries, TL;DR, concepts, tags, limitations, experiments, results, reproduction facts
- **Knowledge Graph** — papers, concepts, tags, citations in a typed Hive graph; relation-typed edge rendering with colors, arrows, dash weights, and filters
- **RAG Search** — chunk + embed pipeline with cosine similarity search over your library
- **Research Notes** — rich vault notes: TL;DR, summary, lineage, limitations & falsification prompts, reproduction checklists, follow-up experiment ideas, figure galleries with captions
- **Experiment Logs** — per-experiment notes with status tracking and a "My Reproduction Log" scaffold (environment, commands, deviations, paper-vs-mine results table)
- **Daily Digest** — one-click digest of what the pool observed, saved to your vault
- **Research Pool** — monitor arXiv topics; observe new papers, batch-import into your KB
- **Web Dashboard** — force-directed graph, landscape view, browsing, similarity matrix, live ingestion activity drawer, logs
- **CLI** — search, add, import, query, `fox`, `digest`, `improve`, GPU monitoring
- **Figure Extraction** — raster dedup by content hash, noise filtering, caption detection, vector-page rendering for matplotlib-style figures
- **Citation Lineage** — automatically fetches and links cited papers
- **Web Ingestion** — add web articles/blog posts as graph nodes
- **Docker** — ready-to-deploy with `docker-compose` (NVIDIA GPU passthrough)

## Requirements

- Python 3.12+
- [Ollama](https://ollama.ai) with models pulled:
  - `llama3.2:3b` (fast tagging)
  - `qwen3.6:35b-mlx` or similar (main analysis)
  - `nomic-embed-text` (embeddings)
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
  ollama_instances:
    gpu_0:
      base_url: http://localhost:11434
      model: qwen3.6:35b-mlx
      embed_model: nomic-embed-text
    gpu_1:
      base_url: http://localhost:11435
      model: llama3.2:3b
      embed_model: nomic-embed-text

graph:
  similarity_threshold: 0.85

rag:
  chunk_size: 512
  chunk_overlap: 64
  top_k: 5
```

Environment variables override Ollama settings: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_FAST_MODEL`, `OLLAMA_EMBED_MODEL`.

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

# Ask Fox (the research companion) from the terminal
python -m hive_research fox "What alignment methods do my papers cover?" --mode deep-research

# Write a digest of new pool papers
python -m hive_research digest --hours 24

# Re-analyze low-rated notes using your criticism as hints
python -m hive_research improve

# Start the web dashboard
python -m hive_research serve --host 0.0.0.0 --port 7777
```

### Web Dashboard

Start the server, then open `http://localhost:7777`:

```
python -m hive_research serve
```

The dashboard provides:
- **Fox** — the research companion: six modes, citation-grounded answers, reasoning traces, survey reports, floating/half/full view modes (`Ctrl/Cmd+K`)
- **Pool** — research pool observatory, daily digests, batch import
- **Graph** — force-directed knowledge graph with relation-colored edges, lineage filters, node preview
- **Import** — add papers by arXiv ID/URL, ingest web articles, search and batch-import
- **Browse** — vault notes with reproduction checklists, figures, experiment logs
- **Similarity** — pairwise similarity matrix (combined/abstract/author/concept)
- **Chat** — classic RAG question-answering
- **About** — system stats, Ollama status, GPU monitoring

### Docker

```bash
docker-compose up --build
```

This launches two Ollama instances (one per GPU), the web server with NVIDIA GPU passthrough, and the Companion agent GUI.

### Companion — Agentic Research GUI (parallel app)

A second web app at `http://localhost:8001` that turns the dashboard into an
**agent**: describe a goal and it plans tool calls over your live library,
executes them under your chosen autonomy level, remembers everything it did
(episodic memory), watches your library in the background for things that need
attention, and learns from every accept/reject to propose better next time.

```bash
python -m uvicorn hive_companion.main:app --port 8001 --app-dir companion/backend
# or: docker compose up -d companion
```

- **Goals & plans** with per-goal autonomy (`approve` / `tiered` / `auto`, switchable mid-run)
- **Approval inbox** — mutating steps pause until you decide
- **Proactive suggestions** ranked by signal strength × learned acceptance weight
- **Episodic memory browser** — searchable record of every action taken
- See [docs/companion.md](docs/companion.md) for architecture and configuration.

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
│  ┌────┴─────┐            ┌──────┴──────┐             │
│  │  LLM     │            │  Embedding  │             │
│  │Interface │            │  (parallel) │             │
│  └────┬─────┘            └──────┬──────┘             │
│       │                         │                    │
│  ┌────┴─────────────────────────┴──────┐             │
│  │          GPUManager                  │             │
│  │    Ollama GPU 0 :11434              │             │
│  │    Ollama GPU 1 :11435              │             │
│  └─────────────────────────────────────┘             │
└─────────────────────────────────────────────────────┘
```

### Modules

| Module | Path | Description |
|--------|------|-------------|
| `arxiv_fetcher` | `hive_research/arxiv_fetcher.py` | arXiv API client: search, fetch by ID, download PDF |
| `parser` | `hive_research/parser.py` | PDF text/figure extraction: noise filtering, hash dedup, caption pairing, vector-page renders |
| `llm` | `hive_research/llm.py` | Ollama client: generate, embed, structured extraction, parallel inference |
| `gpu` | `hive_research/gpu.py` | NVIDIA GPU monitoring (nvidia-smi), Ollama instance lifecycle |
| `graph` | `hive_research/graph.py` | Knowledge graph wrapper around HiveGraph |
| `pipeline` | `hive_research/pipeline.py` | Ingestion pipeline: analysis, graph population, rich notes + experiment logs |
| `rag` | `hive_research/rag.py` | RAG engine: chunking, embedding, cosine similarity, answer generation |
| `fox` | `hive_research/fox.py` | Fox companion: 6 reasoning modes, grounded answers, conversations, survey jobs |
| `feedback` | `hive_research/feedback.py` | Ratings capture + reinforcement signal distillation |
| `jobs` | `hive_research/jobs.py` | Thread-safe job/stage registry for ingestion tracking |
| `domains` | `hive_research/domains.py` | Curated research-domain topic presets |
| `pool` | `hive_research/pool.py` | Research pool: SQLite-backed topic monitoring, arXiv scraping |
| `similarity` | `hive_research/similarity.py` | Paper similarity: author overlap, abstract Jaccard, concept overlap |
| `web_ingest` | `hive_research/web_ingest.py` | Web page ingestion: HTML extraction, LLM analysis, graph addition |
| `organizer` | `hive_research/organizer.py` | Top-level orchestrator: subsystems, auto-improve pass, daily digest |
| `server` | `hive_research/server.py` | HTTP server (stdlib) with REST API + dashboard |
| `logs` | `hive_research/logs.py` | Captured log handler for in-memory log viewing |
| `config` | `hive_research/config.py` | YAML-based configuration with env var overrides |

## Tests

```bash
# stdlib only — no network, no Ollama required
python -m unittest discover -s hive_research/tests -t .
```

## Research Pool

The Research Pool continuously monitors arXiv for topics of interest. It maintains a local SQLite database of observed papers and provides a UI for reviewing and selectively importing them into your knowledge graph.

### Domain Presets

Curated topic packs tuned for AI-safety-adjacent fields (see `hive_research/domains.py`):

| Preset | Focus |
|--------|-------|
| `agents` | LLM agents: tool use, planning, memory |
| `multiagent` | Multi-agent LLM frameworks, debate, MARL |
| `swarms` | Swarm intelligence, emergent communication |
| `alignment` | RLHF, scalable oversight, interpretability |
| `llm-security` | Jailbreaks, prompt injection, backdoors, red-teaming |
| `agentic-security` | Autonomous-agent security, sandboxing, indirect injection |

Enable them in `config.yaml`:

```yaml
workflow:
  domain_presets: [agents, multiagent, swarms, alignment, llm-security, agentic-security]
```

Topics refresh every 12 hours. New papers since the last observation are marked as "new", and the **Daily Digest** button writes everything the pool observed into `data/vault/digests/`.

## The Reinforcement Loop

1. **Capture** — rate Fox answers (👍/👎) and paper notes in Browse; optionally add a comment ("missed the ablation results")
2. **Learn** — Fox distills past criticism into system-prompt hints for future answers
3. **Improve** — run an improvement pass (`⚡ Improve` in Fox, or `python -m hive_research improve`): low-rated notes are re-analyzed with your comments injected as quality requirements
4. **Observe** — every re-analysis is tracked per-stage in the ingestion activity drawer

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
