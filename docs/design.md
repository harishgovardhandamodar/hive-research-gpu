# Design

Detailed diagrams for the subsystems added around the ingest swarm and the audit
ledger. Every diagram is Mermaid source, rendered live in the dashboard's
**About → Documentation** tab and on GitHub.

Each section states the question its diagram answers; together they cover
structure (UML), behaviour (activity, interaction, state), deployment, and the
trust boundaries the system enforces.

## 1. Architecture — containers

*What is in the box, and what talks to what.*

```mermaid
flowchart TB
    subgraph Client["Client · browser (untrusted)"]
        UI["SPA dashboard<br/>dashboard.html"]
    end

    subgraph Host["DGX host · docker compose network_mode:host (trusted)"]
        SRV["HTTP server :7777<br/>RouteHandler"]
        ORG["Organizer"]
        PIPE["PaperPipeline"]
        SW["Agent swarm<br/>5 contracted roles"]
        LED[("Audit ledger<br/>ledger.sqlite3")]
        KG["Knowledge graph"]
        VAULT["Vault · markdown notes"]
        RAGI["RAG index"]
    end

    subgraph Ext["External"]
        ARX["arXiv REST API"]
        GW["fox-services gateway :8210"]
    end

    UI -->|"/api/* + optional HIVE_TOKEN"| SRV
    SRV --> ORG
    ORG --> PIPE
    PIPE --> SW
    PIPE --> LED
    PIPE --> KG
    PIPE --> VAULT
    PIPE --> RAGI
    SW --> GW
    RAGI --> GW
    PIPE -->|"download PDF"| ARX
    SRV -->|"read-only ledger views"| LED
```

## 2. UML — component dependencies

*Which module owns which responsibility, and how they depend.*

```mermaid
flowchart LR
    subgraph agents_pkg["agents.py"]
        RA["run_agent"]
        RES["run_extraction_swarm"]
        VER["run_verifier"]
    end
    subgraph swarm_pkg["swarm.py"]
        RC["ROLE_CONTRACTS"]
        PEP["policy_enforcement_point"]
        TOPO["topology / health / resume_state"]
    end
    subgraph ledger_pkg["ledger.py"]
        APP["append"]
        VCHAIN["verify_chain"]
        CLAIMS["emit_claim / verify_claim"]
    end
    subgraph assur_pkg["assurance_ledger.py"]
        REC["record_*"]
        ALERTS["absence_alerts / integrity_report"]
    end
    subgraph store_pkg["ledger_models.py"]
        STORE["LedgerStore<br/>sqlite3 · WAL"]
    end

    RES --> RA
    RA --> RC
    RA --> REC
    RES --> VER
    RES --> PEP
    VER --> CLAIMS
    VER --> REC
    PEP --> APP
    REC --> APP
    ALERTS --> VCHAIN
    APP --> STORE
    VCHAIN --> STORE
    CLAIMS --> STORE
    TOPO --> REC
```

## 3. UML — class model

*The types an ingest is built from.*

```mermaid
classDiagram
    class Mandate {
        +str objective
        +list allowed_domains
        +list allowed_tools
        +int max_llm_calls
        +int max_events
        +check() Verdict
        +domain_allowed() bool
    }
    class Verdict {
        +str decision
        +str rule
        +str severity
    }
    class LedgerStore {
        +str db_path
        +conn
        +event_row_to_dict() dict
        +record_drop() None
    }
    class Agent {
        +str role
        +str intent
        +tuple fields
        +int max_chars
        +bool fast
        +build_prompt() str
    }
    class AgentContext {
        +str run_id
        +str text
        +dict served_models
        +list claims
        +int llm_calls
    }
    class AgentResult {
        +bool ok
        +dict data
        +str event
        +list empty
    }
    class PaperPipeline {
        +process_paper() dict
        +_analyze_via_swarm() tuple
    }

    Mandate --> Verdict : decides
    Agent --> AgentContext : reads
    AgentContext --> AgentResult : produces
    PaperPipeline --> AgentContext : creates
    AgentResult --> LedgerStore : recorded by
    Mandate --> LedgerStore : persisted in
```

## 4. Activity — one ingest

*What decisions the orchestrator makes, and where it can degrade.*

```mermaid
flowchart TD
    S(["process_paper"]) --> RUN["record run.start + mandate"]
    RUN --> ACQ["fetch + parse PDF"]
    ACQ --> HAS{"source text?"}
    HAS -- no --> DEG(["run.degraded"])
    HAS -- yes --> ROLES["run each contracted role"]
    ROLES --> GOT{"role produced fields?"}
    GOT -- no --> GAP["mark NOT_PRODUCED<br/>record role failure"]
    GOT -- yes --> MERGE["merge declared fields only"]
    GAP --> CHK
    MERGE --> CHK["deterministic grounding<br/>+ model verdicts"]
    CHK --> GATE{"policy gate allowed?"}
    GATE -- no --> DEG
    GATE -- yes --> PUB["graph.write + note.publish"]
    DEG --> FB{"fallback enabled?"}
    FB -- yes --> MONO["single-prompt extraction"]
    FB -- no --> STOP(["no note"])
    MONO --> PUB
    PUB --> ENDC["integrity.check + run.end"]
    ENDC --> E(["done"])
```

## 5. Interaction — verification

*How a number becomes a claim with a verdict, and what is on the chain.*

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant V as Verifier
    participant L as Audit Ledger

    O->>V: run_verifier(merged analysis)
    V->>L: swarm.spawn (verifier)
    V->>V: substring check of every candidate number
    loop each candidate value
        V->>L: claim.emit (verdict, confidence)
    end
    V->>V: model verdict pass (grounding prompt)
    loop each claim
        V->>L: claim.verify (substring + model)
    end
    V->>L: swarm.complete (grounded_ratio, model_error)
    V-->>O: grounding report
    O->>L: gate.check (publish decision)
```

## 6. Interaction — resume from the ledger

*How a restarted process rebuilds state without re-running committed roles.*

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant L as Audit Ledger
    participant W as Role workers

    O->>L: run_events(run_id)
    L-->>O: committed events in chain order
    O->>O: swarm.resume_state(events)
    Note over O: completed roles are skipped,<br/>resume_these are re-run
    O->>W: resume unfinished roles only
    W->>L: append new events
    O->>L: run.end
```

## 7. State — run and claim lifecycles

*How a run and a claim move through states.*

```mermaid
stateDiagram-v2
    [*] --> open: run.start
    open --> open: swarm / llm / claim events
    open --> degraded: run.degraded
    open --> closed: run.end
    degraded --> closed: run.end
    closed --> [*]
```

```mermaid
stateDiagram-v2
    [*] --> unverified: claim.emit
    unverified --> supported: claim.verify floor met
    unverified --> unsupported: claim.verify ungrounded
    supported --> [*]
    unsupported --> [*]
```

## 8. Trust boundaries

*What crosses each boundary, and what protects it.*

```mermaid
flowchart LR
    subgraph Z1["Zone 1 · untrusted client"]
        B["Browser"]
    end
    subgraph Z2["Zone 2 · local app (trusted)"]
        HR["HTTP server"]
        PP["Pipeline + swarm"]
        DB[("Ledger DB")]
        VG["Vault + graph"]
    end
    subgraph Z3["Zone 3 · model provider"]
        G["fox-services gateway"]
    end
    subgraph Z4["Zone 4 · internet"]
        A["arXiv"]
    end

    B -->|"HTTP · optional HIVE_TOKEN"| HR
    HR -.->|"read-only views"| DB
    PP -->|"PDF fetch · source allow-list"| A
    PP -->|"prompts · full text (stored as hashes)"| G
    G -->|"completions + X-Served-Model"| PP
    PP -->|"event data · secrets redacted,<br/>prompts hashed not stored"| DB
    PP -->|"notes with citation + provenance"| VG
```

Boundary controls, in one place:

| Boundary | Data that crosses | Control |
|----------|-------------------|---------|
| Browser → HTTP server | API requests, query params | Optional `HIVE_TOKEN`; path confinement (`_resolve_confined`) |
| Server → Ledger DB | Read-only run/event/claim views | No write path from GET routes |
| Pipeline → arXiv | arXiv ID, PDF request | `swarm_allowed_sources` allow-list |
| Pipeline → Gateway | Paper text, prompts | Redaction in ledger; prompts recorded as hashes (`LEDGER_CAPTURE_PAYLOADS` off) |
| Gateway → Pipeline | Completions, `X-Served-Model` | Requested vs served model both recorded |
| Pipeline → Vault/graph | Note markdown, graph edges | Provenance + confidence in frontmatter |

## 9. Deployment

*Where the pieces run.*

```mermaid
flowchart TB
    subgraph DGX["DGX host · 2× GPU"]
        subgraph Compose["docker compose · network_mode: host"]
            HRC["hive-research-gpu container<br/>:7777"]
            CPC["companion container"]
        end
        VOL[("hive_data volume<br/>graph · vault · pool.db · ledger.sqlite3")]
    end
    subgraph Peer["axiom-1 · Tailscale peer"]
        GW2["fox-services gateway :8210<br/>qwen3.8:27b · llama3.2:3b · nomic-embed-text"]
    end
    BROWSER["Browser / CLI"]

    BROWSER --> HRC
    HRC --> VOL
    CPC --> HRC
    HRC -->|"Tailscale"| GW2
```
