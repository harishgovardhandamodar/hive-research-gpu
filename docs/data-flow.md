# Data Flow

## Paper Ingestion Pipeline

The following diagram traces a single paper through the system:

```
User (CLI or Dashboard)
    │
    ├─ "python -m hive_research add 1706.03762"
    │
    ▼
Organizer.add_by_id("1706.03762")
    │
    ├─ 1. arxiv_fetcher.fetch_by_id_with_meta()
    │      arXiv REST API → PaperInfo
    │
    ├─ 2. pipeline.process_paper(paper)
    │      │
    │      ├─ 2a. kg.add_paper() → Node(type=PAPER)
    │      │
    │      ├─ 2b. download_pdf() → papers/1706.03762.pdf
    │      │
    │      ├─ 2c. parser.extract_text(pdf) → raw text
    │      │
    │      ├─ 2d. parser.extract_images_from_pdf()
    │      │      → figures/ with caption detection
    │      │
    │      ├─ 2e. pipeline._analyze_text(text, title, figures)
    │      │      │
    │      │      ├─ Fast LLM → tags
    │      │      └─ Main LLM → summary, concepts, relations,
    │      │                    notes, experiments, results
    │      │
    │      ├─ 2f. KG population
    │      │      ├─ add_concept() per tag
    │      │      ├─ add_concept() per extracted concept
    │      │      ├─ add_edge() per relation
    │      │      └─ Fuzzy deduplication (Jaccard ≥ 0.85)
    │      │
    │      ├─ 2g. pipeline.fetch_lineage()
    │      │      ├─ Extract arXiv IDs from references
    │      │      ├─ Fetch cited paper metadata
    │      │      ├─ add_paper() + add_edge("cites")
    │      │      └─ Batch save
    │      │
    │      ├─ 2h. pipeline._write_notes_multi()
    │      │      → vault/{title}/00_notes.md
    │      │      → vault/{title}/{experiment}-00-experiment.md
    │      │
    │      └─ 2i. kg.save()
    │
    └─ 3. rag.index_paper(arxiv_id, pdf_text)
           ├─ _chunk_text() → word chunks (512 + 64 overlap)
           ├─ llm.embed_parallel(chunks) → parallel GPU embedding
           ├─ Store in index.json + embeddings.npy
           └─ Append to in-memory chunk list
```

## Query Flow

```
User: "What architectures are used for graph classification?"
    │
    ▼
Organizer.query_rag("...")
    │
    └─ rag.answer("...")
           │
           ├─ rag.search("...")
           │      ├─ llm.embed(query) → query vector
           │      ├─ Cosine similarity with all chunk embeddings
           │      ├─ Top-k results (default 5)
           │      └─ Return chunks with scores
           │
           ├─ Build prompt: context + question
           │
           └─ llm.generate(prompt, temperature=0.0)
                  → Answer with [1], [2] citations
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
