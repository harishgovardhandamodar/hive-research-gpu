# API Reference

The HTTP server exposes a REST API at `http://host:port/api/`.

## GET Endpoints

### `/api/graph`

Knowledge graph in node-link format (for visualization).

```json
{
  "nodes": [{"id": "1706.03762", "label": "Attention Is All You Need", "type": "paper", ...}],
  "links": [{"source": "1706.03762", "target": "transformer", "relation": "introduces"}]
}
```

### `/api/stats`

Combined system statistics.

```json
{
  "papers": 12,
  "graph_papers": 12,
  "concepts": 45,
  "graph_refs": 67,
  "relations": 67,
  "cross_edges": 0,
  "rag": {"chunks": 450, "dimension": 768, "papers": 12}
}
```

### `/api/similarity`

Paper similarity matrix. Optional query params: `paper_ids` (comma-separated), `algorithm`.

```json
GET /api/similarity?algorithm=combined&paper_ids=1706.03762,2106.09685
```

### `/api/papers`

List all papers in the knowledge graph.

```json
[
  {
    "id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": "Vaswani et al.",
    "published": "2017-06-12",
    "note_path": "data/vault/attention_is_all_you_need/00_notes.md",
    "has_lineage": true,
    "has_extra": true
  }
]
```

### `/api/papers/search?q=...`

Search papers by title, author, or affiliation.

### `/api/concepts`

List all concept nodes.

```json
[
  {"id": "transformer", "label": "Transformer", "definition": "A neural network architecture..."}
]
```

### `/api/browse`

File tree of `papers/` and `vault/` directories.

### `/api/read?path=...`

Read a file from `papers/` or `vault/` by relative path. Returns file content as JSON.

### `/api/raw?path=...`

Serve raw file content (images, PDFs, markdown) with appropriate Content-Type.

### `/api/web/list`

List ingested web resources.

### `/api/ollama`

Hive Serving cluster health and model availability.

```json
{
  "connected": true,
  "hive_url": "http://localhost:8081",
  "backend": "hive-server-go",
  "model": "qwen3.6:35b-mlx",
  "model_available": true,
  "platform": "Linux-...",
  "python": "3.12.4"
}
```

### `/api/gpu`

GPU status (CUDA or nvidia-smi).

### `/api/logs?n=100`

Recent application logs.

### `/api/pool`

Research pool feed (topic → papers).

### `/api/pool/papers`

All observed pool papers.

### `/api/pool/graph`

Pool similarity graph.

### `/api/pool/topics`

List of monitored topics.

## POST Endpoints

### `/api/add`

Add a paper by arXiv ID.

```json
POST /api/add
{"id": "1706.03762", "model": "fast"}
```

Optional field: `model` (string) — analysis model to use. Accepts `"large"` (default), `"fast"`, or any model name.

### `/api/search`

Search arXiv (no import).

```json
POST /api/search
{"query": "transformer attention"}
```

### `/api/import`

Search and import papers.

```json
POST /api/import
{"query": "graph neural networks", "model": "fast"}
```

Optional field: `model` (string) — analysis model (same semantics as `/api/add`).

### `/api/query`

RAG question answering.

```json
POST /api/query
{"question": "What architectures are used for graph classification?"}
```

### `/api/lineage`

Fetch citation lineage for a paper.

```json
POST /api/lineage
{"arxiv_id": "1706.03762"}
```

### `/api/web/add`

Ingest a web URL as a graph node.

```json
POST /api/web/add
{"url": "https://example.com/blog/post", "model": "large"}
```

Optional field: `model` (string) — analysis model (same semantics as `/api/add`).

### `/api/similarity`

Compute similarity matrix with optional filters and result limiting.

```json
POST /api/similarity
{"paper_ids": ["1706.03762", "2106.09685"], "algorithm": "abstract", "top_k": 10}
```

Optional field: `top_k` (int) — limit results to top-K pairs (significantly improves performance).

### `/api/refresh`

Refresh notes for all papers missing them.

```json
POST /api/refresh
{"model": "fast"}
```

Optional field: `model` (string) — analysis model. Accepts `"large"` (default), `"fast"`, or any model name.

### `/api/papers/refresh`

Refresh notes for a single paper.

```json
POST /api/papers/refresh
{"paper_id": "1706.03762", "model": "fast"}
```

Optional field: `model` (string) — analysis model (same semantics as `/api/refresh`).

### `/api/definitions`

Auto-generate definitions for concept nodes without them.

### `/api/pool/topics/add`

Add a research topic.

```json
POST /api/pool/topics/add
{"name": "Mixture of Experts", "query": "mixture of experts"}
```

### `/api/pool/topics/remove`

Remove a research topic.

```json
POST /api/pool/topics/remove
{"name": "AI alignment"}
```

### `/api/pool/import`

Import a paper from the pool into the graph.

```json
POST /api/pool/import
{"arxiv_id": "2409.13004"}
```

### `/api/pool/import_batch`

Batch import papers from the pool.

```json
POST /api/pool/import_batch
{"arxiv_ids": ["2409.13004", "2409.13005"]}
```

### `/api/query`

RAG question answering with search mode selection.

```json
POST /api/query
{"question": "What is the transformer architecture?", "mode": "hybrid"}
```

Optional field: `mode` (string) — `"vector"` (semantic), `"keyword"` (BM25), or `"hybrid"` (RRF fusion). Default: `"hybrid"`.

### `/api/collections`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/collections` | GET | List all collections |
| `/api/collections/papers?collection=` | GET | Get papers in a collection |
| `/api/collections/create` | POST | `{"name", "description"}` |
| `/api/collections/delete` | POST | `{"name"}` |
| `/api/collections/add` | POST | `{"collection", "paper_id"}` |
| `/api/collections/remove` | POST | `{"collection", "paper_id"}` |

### `/api/favorites`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/favorites` | GET | List favorite paper IDs |
| `/api/favorites/add` | POST | `{"paper_id"}` |
| `/api/favorites/remove` | POST | `{"paper_id"}` |

### `/api/searches`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/searches` | GET | List saved searches |
| `/api/searches/save` | POST | `{"query", "name"}` |
| `/api/searches/delete` | POST | `{"index"}` |

### Export Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/export/bibtex` | GET | Download BibTeX file (`papers.bib`) |
| `/api/export/json` | GET | Download graph JSON |
| `/api/export/csv` | GET | Download papers CSV (`papers.csv`) |
| `/api/export/backup` | GET | Download backup ZIP |

### Ingestion Queue Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingestion/queue` | GET | All jobs with current status |
| `/api/ingestion/events?since=&n=` | GET | Status change events |
| `/api/ingestion/stats` | GET | Job counts by status |
| `/api/ingestion/add` | POST | Enqueue paper `{"id":"1706.03762","model":"fast"}` |
| `/api/ingestion/clear` | POST | Clear completed/failed jobs |

### Pool Query

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pool/query` | POST | Free-form natural language query `{"query":"..."}` |
| `/api/pool/insights` | GET | Topic performance and conversion stats |
| `/api/pool/suggestions?paper_id=X` | GET | Similar papers from the pool |

### Duplicate Detection

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/papers/duplicates?paper_id=X` | GET | Find duplicates for a paper |
| `/api/papers/duplicates` | GET | Find all duplicate groups |
