# Data Flow

## Paper Ingestion Pipeline

The following diagram traces a single paper through the system:

```mermaid
flowchart TD
    U["User · CLI or Dashboard<br/>python -m hive_research add 1706.03762"] --> FETCH["arxiv_fetcher.fetch_by_id_with_meta()<br/>arXiv REST API → PaperInfo"]
    FETCH --> PIPE["pipeline.process_paper(paper)"]

    PIPE --> KT["kg.add_paper() → Node(type=PAPER)"]
    PIPE --> DL["download_pdf() → papers/1706.03762.pdf"]
    PIPE --> TX["parser.extract_text(pdf) → raw text"]
    PIPE --> IMG["parser.extract_images_from_pdf()<br/>figures/ + caption detection"]
    PIPE --> SW["agents.run_extraction_swarm()<br/>5 contracted roles → summary, tags, concepts,<br/>relations, experiments, results"]
    PIPE --> LG["Audit Ledger<br/>roles · models · claims · chain"]

    SW --> KG["Knowledge Graph population<br/>add_concept() per tag/concept<br/>add_edge() per relation<br/>fuzzy dedup Jaccard ≥ 0.85"]
    SW --> LIN["fetch_lineage()<br/>cited arXiv IDs → cites edges"]
    PIPE --> NOTE["_write_notes_multi()<br/>vault/title/00_notes.md<br/>+ per-experiment notes"]
    PIPE --> SAVE["kg.save()"]
    PIPE --> RAGI["rag.index_paper()<br/>chunk 512/64 · embed_parallel<br/>index.json + embeddings.npy"]
```

## Query Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant O as Organizer
    participant R as RAGEngine
    participant L as LLM Interface

    U->>O: query_rag("What architectures are used for graph classification?")
    O->>R: answer(question)
    R->>L: embed(question)
    L-->>R: query vector
    R->>R: cosine similarity · top-k (default 5)
    R->>L: generate(context + question, temperature=0.0)
    L-->>R: answer with [1], [2] citations
    R-->>U: answer + source chunks
```

## Research Pool Flow

```
Background thread (every 12 hours)
    │
    └─ pool._bg_refresh()
           │
           ├─ For each topic:
           │      search_arxiv(topic.query, max_results=10)
           │      │
           │      ├─ For each result:
           │      │      ├─ If existing: update last_seen, append topic
           │      │      └─ If new: INSERT with first_seen=now
           │      │
           │      └─ Cache result in SQLite with TTL
           │
           └─ Dashboard fetches pool.get()
                  → Returns cached feed or triggers background refresh
```

## Web Ingestion Flow

```
User: Paste URL → Click "Ingest"
    │
    ▼
web.ingest(url)
    │
    ├─ HTTP GET → HTML
    ├─ extract_title(), extract_description()
    ├─ extract_text_content() (strip HTML tags)
    ├─ extract_images(), extract_links()
    ├─ LLM analysis: summary, tags, concepts
    ├─ add_paper(paper_id, title, abstract=summary)
    │  (node.type = "web")
    ├─ add_concept() per tag and concept
    ├─ add_edge() connections
    └─ kg.save()
```

## Graph Data Model

```
Node types:
  - PAPER:  arXiv paper with title, authors, abstract, categories
  - CONCEPT: Extracted concept/tag with definition
  - (web):  Web resource with URL in affiliations field

Edge types:
  - related_to:  Paper ↔ Concept (default)
  - cites:       Paper → Paper (citation lineage)
  - introduces:  Paper → Concept (custom)
  - uses:        Paper → Concept (custom)
  - proposes:    Paper → Concept (custom)
```
