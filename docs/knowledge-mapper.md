# Agentic Knowledge Mapper — investigation addon

Sibling app at `../agentic-knowledge-mapper`, wired into this stack as the
`knowledge-mapper` (+ `mapper-standards`) compose services. It is independent
of the hive library: it runs its own collection loop, SQLite store, and audit
ledger, and shares only the local LLM gateway with this repo.

```
┌──────────────────────────────┐   OpenAI-compat /v1
│ knowledge-mapper (:8209→8204)│ ──────────────────────▶ gateway (:8210/v1)
│  collection · explainer ·    │ ▶ fallback (:11434/v1)   Ollama / mesh peers
│  security (A2A) · ledger     │   via host.docker.internal
└──────────▲───────────────────┘
           │ static GUI + iframe (:5173)
┌──────────┴───────────────────┐
│ browser (:8209)              │ ──▶ standalone :5173 (iframe, hardcoded)
│                              │     ours :5174 (direct access)
└──────────────────────────────┘
```

Side-by-side: the sibling's standalone stack keeps `:8204`/`:5173`, so this
copy serves the GUI on `:8209` (bridge → container `:8204`) with its own
`akm_data` volume. The GUI's Standards-tab iframe is hardcoded to
`<host>:5173`, i.e. it shows the standalone dashboard; our `:5174` copy is
for direct access.

## Run

```bash
# from this repo; requires the sibling checkout at ../agentic-knowledge-mapper
# macOS / Apple Silicon uses the MLX build — export once before compose up
# (the in-file compose default is the Linux model).
[ "$(uname -s)" = "Darwin" ] && export LLM_MODEL=qwen3.8:27b-mlx LLM_FALLBACK_MODEL=qwen3.8:27b-mlx
docker compose up -d --build knowledge-mapper mapper-standards

curl http://localhost:8209/api/health  # app + which LLM backend is active
# GUI at http://localhost:8209 — Standards dashboard (direct) at http://localhost:5174

### Reaching the GUI

- Direct: `http://localhost:8209`
- From the main dashboard: the sidebar **Knowledge Mapper** entry (layers
  icon, below Fox Companion), or open `http://localhost:7777/mapper` — it
  302-redirects to the GUI. Set `MAPPER_URL` on the main server to override
  the target (e.g. `MAPPER_URL=http://localhost:8204/` to point at the
  sibling's standalone stack instead).
```

Local dev (without Docker), from the sibling repo:

```bash
cd ../agentic-knowledge-mapper
pip install -r requirements.txt
LLM_BASE_URL=http://localhost:8210/v1 python -m uvicorn app.main:app --port 8204 --reload
```

## Configuration

| Variable | Linux default | macOS (Apple Silicon) default | Description |
|----------|---------------|-------------------------------|-------------|
| `LLM_BASE_URL` | `http://host.docker.internal:8210/v1` | same | Primary OpenAI-compat backend (local gateway, container-side) |
| `LLM_FALLBACK_URL` | `http://host.docker.internal:11434/v1` | same | Fallback Ollama backend (container-side) |
| `LLM_MODEL` | `qwen3.8:27b` | `qwen3.8:27b-mlx` | Model on the primary backend |
| `LLM_FALLBACK_MODEL` | `qwen3.8:27b` | `qwen3.8:27b-mlx` | Model name on the fallback backend |
| `LLM_TIMEOUT_S` | `180` | Per-request LLM timeout |

Data persists in the `akm_data` volume (`/app/data` → `akm.db`); runtime
state is git-ignored upstream and never committed.

## What it does

- **Investigations** — keywords + brief, per-query sources (`rss,arxiv,web`), cron re-runs, hide-instead-of-delete.
- **Agent loop** — `PLAN → SEARCH → ANALYZE → MAP → REFINE`, streamed as `AgentEvent`s (`GET /api/runs/{id}/events`).
- **Knowledge graph** — per-investigation artifacts + typed relationships (`references · supports · contradicts · builds_upon · responds_to · similar_to`).
- **Explainer** — modes (explain/deep-dive/compare/tutor/critique/tldr/glossary/api-ref), grounded claims with verbatim-quote verification, threads/quiz/watch.
- **AI Security agent** — product + exposure scoping, scored report, Markdown/PDF export.
- **Audit ledger** — hash-chained runs, mandates/approvals, session spines, claim grounding, self-verifying exports.

Full design docs live upstream: `../agentic-knowledge-mapper/docs/`
(`architecture.md`, `agent-loop.md`, `explainer.md`, `security-agent.md`,
`data-model.md`, `frontend.md`, `operations.md`).
