# Module Reference

## `hive_research.arxiv_fetcher`

arXiv API client built on the `arxiv` Python library.

```python
from hive_research.arxiv_fetcher import search_arxiv, fetch_by_id, download_pdf
```

| Function | Description |
|----------|-------------|
| `search_arxiv(query, max_results=10)` | Search arXiv and return `list[PaperInfo]` |
| `fetch_by_id(arxiv_id)` | Fetch single paper by arXiv ID, returns `PaperInfo` or `None` |
| `fetch_by_id_with_meta(arxiv_id)` | Like `fetch_by_id` but returns `dict` with status |
| `download_pdf(arxiv_id, target_dir)` | Download PDF to `target_dir/{id}.pdf`, returns `Path` or `None` |
| `parse_arxiv_id(text)` | Extract arXiv ID from arbitrary text |
| `extract_arxiv_ids(text)` | Extract all arXiv IDs from text |

**`PaperInfo`** — Wraps `arxiv.Result` with convenience properties: `arxiv_id`, `title`, `authors` (list with affiliations), `authors_str`, `affiliations_str`, `abstract`, `published`, `categories`, `pdf_url`.

## `hive_research.parser`

PDF text and figure extraction via PyMuPDF.

| Function | Description |
|----------|-------------|
| `extract_text(pdf_path)` | Extract all text from PDF |
| `extract_metadata(pdf_path)` | Extract PDF metadata (title, author, subject) |
| `extract_sections(text)` | Split text into sections by heading patterns |
| `extract_images_from_pdf(pdf_path, output_dir)` | Extract figures/tables with caption detection |
| `extract_references(text)` | Extract numbered references from text |
| `extract_referenced_arxiv_ids(text)` | Extract arXiv IDs from reference section |

Figure extraction heuristics: filters images below 100px or 2KB, detects captions near image boundaries using `Fig(ure)`, `Table`, and `Algorithm` keywords.

## `hive_research.llm`

Ollama client for generation, structured extraction, and embedding.

```python
from hive_research.llm import LLMInterface
llm = LLMInterface(config, gpu_mgr)
```

| Method | Description |
|--------|-------------|
| `generate(prompt, model, system, temperature, max_tokens, gpu_id)` | Text generation |
| `generate_parallel(prompts, ...)` | Concurrent generation across GPUs |
| `extract_structured(prompt, model, gpu_id)` | JSON extraction with repair fallback |
| `embed(text, model, gpu_id)` | Single text embedding |
| `embed_parallel(texts, model)` | Batch embedding across GPUs |
| `chat(messages, model, gpu_id)` | Chat completion endpoint |
| `health_check(gpu_id)` | Check if Ollama instance is reachable |

JSON repair handles truncated responses, trailing commas, unquoted values, missing closing brackets.

## `hive_research.gpu`

NVIDIA GPU monitoring and Ollama instance lifecycle.

```python
from hive_research.gpu import GPUManager
gpu_mgr = GPUManager(config)
```

| Method | Description |
|--------|-------------|
| `get_devices()` | List of `GPUDevice` objects with current metrics |
| `get_device(index)` | Single device info |
| `get_status()` | Dict with device count, per-device memory/util/temp/power |
| `get_next_llm_gpu()` | Round-robin GPU assignment for LLM |
| `get_next_embed_gpu()` | Round-robin GPU assignment for embedding |
| `device_count()` | Number of detected GPUs |
| `launch_ollama_instances()` | Start one Ollama `serve` process per GPU |
| `get_ollama_url(gpu_id)` | URL for GPU-specific Ollama instance |

Background monitor thread refreshes `nvidia-smi` data every 5 seconds.

## `hive_research.graph`

Knowledge graph wrapper around `HiveGraph` (from `hive-datatype`).

```python
from hive_research.graph import KnowledgeGraph
kg = KnowledgeGraph(config, graph_id="main")
```

| Method | Description |
|--------|-------------|
| `add_paper(paper_id, title, ...)` | Add or retrieve a paper node |
| `add_concept(concept_id, label, ...)` | Add or retrieve a concept node |
| `add_edge(source, target, relation)` | Add a typed edge between nodes |
| `find_similar_concept(label, threshold)` | Fuzzy Jaccard match against existing concepts |
| `get_paper(paper_id)` | Retrieve paper node by ID |
| `get_concept(concept_id)` | Retrieve concept node by ID |
| `save()` | Persist graph to JSON |
| `stats()` | Paper/concept/edge counts |
| `to_node_link()` | Node-link dict for visualization |

Concept deduplication uses token Jaccard similarity with configurable threshold (default 0.85).

## `hive_research.pipeline`

Paper ingestion pipeline.

```python
from hive_research.pipeline import PaperPipeline
pipeline = PaperPipeline(config, llm, kg, gpu_mgr)
```

| Method | Description |
|--------|-------------|
| `process_paper(paper, gpu_id, model)` | Full ingestion: download → analyze → graph → notes |
| `process_papers_parallel(papers, model)` | Concurrent ingestion across GPUs |
| `fetch_lineage(paper_id, pdf_text, max_refs)` | Extract citations and link prior work |
| `_analyze_text(text, title, figures, model)` | LLM analysis: tags, concepts, summary, experiments |

## `hive_research.rag`

Retrieval-Augmented Generation engine.

```python
from hive_research.rag import RAGEngine
rag = RAGEngine(config, llm, kg)
```

| Method | Description |
|--------|-------------|
| `index_paper(paper_id, text)` | Chunk + embed + store; returns chunk count |
| `search(query, top_k)` | Cosine similarity search; returns chunks with scores |
| `answer(query)` | Retrieve + LLM generate answer with citations |
| `stats()` | Chunk count, embedding dimension, paper count |

## `hive_research.pool`

Research topic monitoring with SQLite persistence.

```python
from hive_research.pool import ResearchPool
pool = ResearchPool(store_dir)
```

| Method | Description |
|--------|-------------|
| `get()` | Cached feed of topic → papers |
| `refresh()` | Force immediate refresh |
| `get_topics()` | List of monitored topics |
| `add_topic(name, query)` | Add a topic to monitor |
| `remove_topic(name)` | Remove a topic |
| `get_observed_papers()` | All observed papers with import/new status |
| `mark_imported(arxiv_id)` | Mark paper as imported into graph |
| `get_pool_graph()` | Paper graph with Jaccard edge similarity |

## `hive_research.similarity`

Paper similarity computation.

```python
from hive_research.similarity import paper_similarity_matrix
```

| Function | Description |
|----------|-------------|
| `paper_similarity_matrix(kg, paper_ids, algorithm)` | Pairwise similarity scores |
| `jaccard_tokens(a, b)` | Token Jaccard similarity |
| `shared_concepts(kg, paper_a, paper_b)` | Overlapping graph concepts |

Algorithms: `combined` (default), `abstract`, `author`, `concept`.

## `hive_research.web_ingest`

Web page ingestion into the knowledge graph.

```python
from hive_research.web_ingest import WebIngester
web = WebIngester(llm, kg)
```

| Method | Description |
|--------|-------------|
| `ingest(url, model)` | Fetch URL → extract title/content/images → LLM analysis → graph addition |

## `hive_research.organizer`

Top-level orchestrator that wires all subsystems together.

```python
from hive_research.organizer import Organizer
org = Organizer(config, gpu_mgr)
```

| Method | Description |
|--------|-------------|
| `add_by_id(arxiv_id, model)` | Fetch + process + RAG index a single paper |
| `add_by_search(query, max_results, model)` | Search + process multiple papers |
| `search(query, max_results)` | arXiv search (no import) |
| `query_rag(question)` | RAG question answering |
| `similarity(paper_ids, algorithm)` | Paper similarity matrix |
| `stats()` | Combined graph + RAG + GPU stats |
| `graph_data()` | Node-link graph for visualization |
| `fetch_lineage(arxiv_id)` | Citation lineage for a paper |
| `refresh_papers(model)` | Regenerate notes for papers missing them |
| `refresh_paper(paper_id, model)` | Regenerate notes for a single paper |
| `generate_definitions()` | Auto-generate definitions for concept nodes without them |
| `notes_path_for(paper_id)` | Path to vault notes for a paper |

## `hive_research.server`

HTTP server with REST API and SPA dashboard.

```python
from hive_research.server import run_server
run_server(org, gpu_mgr, host="0.0.0.0", port=7777)
```

See [API Reference](../api.md) for full endpoint documentation.

## `hive_research.config`

YAML configuration reader.

```python
from hive_research.config import Config
cfg = Config("config.yaml")
cfg.ollama_model        # → "qwen3.6:35b-mlx"
cfg.gpu_device_count    # → 2
cfg.rag_chunk_size      # → 512
```

| Method | Description |
|--------|-------------|
| `resolve_model(model)` | Map `None`/`""`/`"large"` → `ollama_model`, `"fast"` → `ollama_fast_model`, else passthrough |

All properties have sensible defaults and support environment variable overrides.

## `hive_research.logs`

In-memory log capture for the dashboard.

```python
from hive_research.logs import get_capture
capture = get_capture()
capture.get_recent(100)  # Last 100 log entries
```
