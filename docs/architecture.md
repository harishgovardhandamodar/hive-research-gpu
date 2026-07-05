# Hive Research GPU — Architecture

```mermaid
graph TB
    subgraph Interface["Interface Layer"]
        CLI["CLI (__main__.py)\nsearch / add / import / query\nstats / gpu / export / serve"]
        API["REST API (server.py)\n:7777 /api/* endpoints"]
        UI["SPA Dashboard\nindex.html + dashboard.html"]
        NB["Jupyter Notebooks\nnotebooks/"]
    end

    subgraph Orchestration["Orchestration Layer"]
        ORG["Organizer\nTop-level orchestrator\nwires all subsystems together"]
    end

    subgraph Core["Core Engine"]
        KG["KnowledgeGraph\nHiveGraph nodes + edges\npapers, concepts, web resources"]
        LLM["LLMInterface\nOllama client\nchat, embed, extract_structured"]
        RAG["RAGEngine\nVector + BM25 + Hybrid (RRF)\nFAISS (optional)"]
        SIM["Similarity\nPaper similarity algorithms\ncombined, abstract, author, vector"]
        PL["Pipeline\nPaper ingestion\nfetch → PDF → LLM → graph → RAG"]
    end

    subgraph Storage["Storage & Data"]
        GRAPH["graph/main.json\nHiveGraph JSON"]
        PDFS["papers/*.pdf\nDownloaded PDFs"]
        VAULT["vault/{title}/\nMarkdown notes + figures"]
        RAG_STORE["rag/\nindex.json + embeddings.npy"]
        POOL_DB["pool/pool.db\nSQLite"]
        CONFIG["config.yaml\nConfiguration"]
        COLL["collections.json\nUser collections + favorites"]
    end

    subgraph Support["Support Services"]
        EXPO["Exporter\nBibTeX, JSON, CSV, ZIP"]
        COLLS["Collections\nPaper collections\nFavorites, saved searches"]
        SCHEMAS["Schemas\nPydantic models\nInput validation"]
        CLIENT["Client\nHiveClient\nPython library"]
        GPU["GPUManager\nnvidia-smi monitoring\nOllama lifecycle"]
        POOL["ResearchPool\narXiv topic monitoring\nSQLite-backed"]
        WEB["WebIngester\nURL fetching + LLM extraction"]
        ARXIV["ArXivFetcher\narXiv API client"]
        PARSER["Parser\nPDF text + figure extraction"]
    end

    CLI --> ORG
    API --> ORG
    UI --> API
    NB --> API
    NB --> CLIENT
    CLIENT --> API
    CLIENT --> ORG

    ORG --> KG
    ORG --> LLM
    ORG --> RAG
    ORG --> PL
    ORG --> POOL
    ORG --> WEB
    ORG --> GPU
    ORG --> EXPO
    ORG --> COLLS

    PL --> ARXIV
    PL --> PARSER
    PL --> LLM
    PL --> KG
    PL --> RAG

    KG --> GRAPH
    PARSER --> PDFS
    PL --> VAULT
    RAG --> RAG_STORE
    POOL --> POOL_DB
    COLLS --> COLL
    ORG --> CONFIG

    SIM --> KG
    RAG --> KG
    RAG --> LLM
    WEB --> LLM
    WEB --> KG
```

## Data Flow: Paper Ingestion

```mermaid
sequenceDiagram
    participant User
    participant CLI/API/UI
    participant Orchestrator as Organizer
    participant ArXiv
    participant Parser
    participant LLM
    participant Graph as KnowledgeGraph
    participant RAG

    User->>CLI/API/UI: Add paper 1706.03762
    CLI/API/UI->>Orchestrator: add_by_id()
    Orchestrator->>ArXiv: fetch_by_id()
    ArXiv-->>Orchestrator: Paper metadata
    Orchestrator->>ArXiv: download_pdf()
    ArXiv-->>Orchestrator: PDF file
    Orchestrator->>Parser: extract_text()
    Parser-->>Orchestrator: Plain text
    Orchestrator->>LLM: extract tags (fast model)
    LLM-->>Orchestrator: Tags
    Orchestrator->>LLM: extract concepts + relations (main model)
    LLM-->>Orchestrator: Concepts, relations, summary
    Orchestrator->>Graph: add_paper(), add_concept(), add_edge()
    Orchestrator->>RAG: index_paper()
    RAG-->>Orchestrator: Chunks indexed
    Orchestrator-->>CLI/API/UI: {status: "added", ...}
```

## Data Flow: RAG Query

```mermaid
sequenceDiagram
    participant User
    participant API
    participant RAG as RAGEngine
    participant LLM

    User->>API: /api/query {question, mode}
    API->>RAG: answer(question, mode="hybrid")

    alt Hybrid mode
        RAG->>RAG: search_vector() (FAISS/numpy)
        RAG->>RAG: search_keyword() (BM25)
        RAG->>RAG: RRF fusion of results
    else Vector mode
        RAG->>RAG: search_vector()
    else Keyword mode
        RAG->>RAG: search_keyword()
    end

    RAG->>LLM: generate(context + question)
    LLM-->>RAG: Answer with citations
    RAG-->>API: {answer, sources}
    API-->>User: JSON response
```

## Module Dependency Graph

```mermaid
graph LR
    __main__ --> organizer
    server --> organizer
    client --> organizer
    client --> server

    organizer --> config
    organizer --> graph
    organizer --> llm
    organizer --> pipeline
    organizer --> rag
    organizer --> pool
    organizer --> web_ingest
    organizer --> exporter
    organizer --> collections

    pipeline --> arxiv_fetcher
    pipeline --> parser
    pipeline --> llm
    pipeline --> graph

    rag --> config
    rag --> llm
    rag --> graph

    similarity --> graph

    web_ingest --> llm
    web_ingest --> graph

    llm --> config
    llm --> gpu

    gpu --> config
    pool --> config
    exporter --> config
    exporter --> graph
    collections --> graph

    schemas --> server

    style organizer fill:#60a5fa,color:#000
    style server fill:#34d399,color:#000
    style client fill:#fbbf24,color:#000
```

## Data Storage Layout

```
data/
├── papers/           # Downloaded PDFs (arXiv ID + .pdf)
│   ├── 1706.03762.pdf
│   └── 1706.03762.txt          # Cached extracted text (sidecar)
├── graph/
│   └── main.json               # HiveGraph JSON (nodes + edges)
├── vault/                       # Markdown notes
│   └── attention_is_all_you_need/
│       ├── 00_notes.md          # Paper notes + YAML frontmatter
│       ├── 01-experiment.md     # Per-experiment notes
│       └── figures/             # Extracted figures
│           ├── figure_p01_01.png
│           └── ...
├── rag/
│   ├── index.json              # Chunk index (text, source, chunk_idx)
│   └── embeddings.npy          # Dense embedding matrix (numpy)
├── pool/
│   └── pool.db                 # Research pool SQLite database
├── backups/                    # ZIP backups (created via export)
│   └── hive_backup_20250123.zip
└── collections.json            # Paper collections + favorites
```
