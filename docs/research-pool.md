# Research Pool

The Research Pool is a background system that continuously monitors arXiv for topics of interest, surfacing new papers for selective import into your knowledge graph.

## Architecture

- **SQLite database** (`data/pool/pool.db`) stores topics, observed papers, and a cached feed
- **Background scheduler** refreshes all topics every 12 hours
- **TTL cache** (12 hours) in the `cache` table prevents redundant refreshes
- **Thread-safe** with `threading.local` per-thread SQLite connections and WAL journal mode

## Default Topics

| Name | arXiv Query |
|------|-------------|
| Knowledge graphs | `knowledge graph embedding` |
| Federated learning | `federated learning` |
| AI security | `AI security adversarial machine learning` |
| LLM security | `large language model security` |
| AI alignment | `AI alignment` |
| Adversarial ML | `adversarial machine learning` |
| Graph neural networks | `graph neural network` |
| Vision-language models | `vision language model` |

## Adding Custom Topics

### Via Dashboard

1. Go to the **Pool** panel
2. Click the gear icon → Topics tab
3. Enter a name and arXiv query
4. Click Add Topic

### Via CLI / API

```python
from hive_research.pool import ResearchPool
pool = ResearchPool("./data/pool")
pool.add_topic("Mixture of Experts", "mixture of experts transformer")
pool.remove_topic("AI alignment")
```

## Data Model

### `topics` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `name` | TEXT | Unique topic name |
| `query` | TEXT | arXiv search query |
| `created_at` | TEXT | ISO timestamp |

### `papers` table

| Column | Type | Description |
|--------|------|-------------|
| `arxiv_id` | TEXT | Primary key |
| `title` | TEXT | Paper title |
| `authors` | TEXT | JSON array of author objects |
| `authors_str` | TEXT | Comma-separated author names |
| `published` | TEXT | Publication date |
| `abstract` | TEXT | Abstract (first 500 chars) |
| `categories` | TEXT | JSON array of arXiv categories |
| `pdf_url` | TEXT | PDF download URL |
| `topics` | TEXT | JSON array of matching topic names |
| `tags` | TEXT | JSON array of LLM-extracted tags |
| `imported` | INTEGER | 0 = not imported, 1 = imported |
| `imported_at` | TEXT | ISO timestamp of import |
| `first_seen` | TEXT | When first observed |
| `last_seen` | TEXT | When last observed |

## Pool Graph

The pool generates a similarity graph based on token Jaccard similarity over titles + abstracts. Edges are created when similarity ≥ 0.12. This helps identify clusters of related papers within the pool.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pool` | GET | Cached feed (topic → papers) |
| `/api/pool/papers` | GET | All observed papers with status |
| `/api/pool/graph` | GET | Pool similarity graph |
| `/api/pool/topics` | GET | List of monitored topics |
| `/api/pool/topics/add` | POST | Add a topic |
| `/api/pool/topics/remove` | POST | Remove a topic |
| `/api/pool/import` | POST | Import a single paper from pool |
| `/api/pool/import_batch` | POST | Import multiple papers |
