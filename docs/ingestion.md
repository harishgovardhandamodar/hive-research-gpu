# Ingestion Queue

The ingestion queue provides async paper ingestion with per-paper status tracking. When papers are added via the API or CLI, they enter a queue and are processed in the background by a worker thread.

## Status Lifecycle

```
queued → fetching → downloading → extracting → parsing → analyzing → graphing → indexing → done
                                                                                             → error
```

Each paper transitions through these stages with status updates broadcast to:
- The **in-memory event buffer** (polled by the dashboard)
- The **standard Python logging** system (appears in the Activity Log)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingestion/queue` | GET | All jobs with current status |
| `/api/ingestion/events?since=&n=` | GET | Status change events (optional time filter) |
| `/api/ingestion/stats` | GET | Count of jobs by status |
| `/api/ingestion/add` | POST | Enqueue a paper `{"id":"1706.03762","model":"fast"}` |
| `/api/ingestion/clear` | POST | Remove completed/failed jobs from the queue |

## Status Response

```json
{
  "paper_id": "1706.03762",
  "model": null,
  "status": "indexing",
  "progress": 75,
  "message": "Indexing for RAG search",
  "started": "2025-01-23T21:30:15",
  "finished": null,
  "error": null
}
```

## Activity Log Format

```
21:30:15 [INFO] hive_research.ingestion: 1706.03762:fetching — Fetching metadata from arXiv
21:30:17 [INFO] hive_research.ingestion: 1706.03762:downloading — Downloading PDF
21:30:20 [INFO] hive_research.ingestion: 1706.03762:extracting — Extracting text from PDF
21:30:35 [INFO] hive_research.ingestion: 1706.03762:indexing — Indexing for RAG search
21:30:38 [INFO] hive_research.ingestion: 1706.03762:done — Added: 5 concepts, 3 tags
```

## Dashboard Status Bar

The ingestion queue status bar appears below the main panels showing:
- Active job count + completed job count
- Color-coded badges: ◌ queued (gray), ● in-progress (blue), ✓ done (green), ✗ error (red)
- Each badge shows `paper_id:status` with hover tooltip

## Architecture

```
POST /api/add
    │
    ▼
IngestionQueue.enqueue(paper_id)
    │
    ▼
Worker thread picks up job
    │
    ├── 1. Fetch metadata from arXiv
    ├── 2. Download PDF
    ├── 3. Extract text
    ├── 4. LLM analysis (tags, concepts, relations)
    ├── 5. Populate knowledge graph
    └── 6. Index for RAG search
         │
         ▼
    Status: done / error
```
