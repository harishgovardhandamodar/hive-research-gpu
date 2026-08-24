# Fox Companion — the agentic GUI

A parallel web app for hive-research: an agent with **episodic memory**, a
**proactive engine**, and **reinforcement loops** that learns your preferences
and automates research workflows. It drives the main app exclusively through
its HTTP API, so there is exactly one writer to your library.

```
┌──────────────────────────────┐   HTTP (existing 40+ endpoints)
│ companion (FastAPI :8001)    │ ────────────────────────────────────▶ hive server (:7777)
│  planner · executor ·        │                                      library, KG, RAG,
│  episodic store · policy ·   │                                      fox, pool, feedback
│  proactive watcher           │
└──────────▲───────────────────┘
           │ REST + WebSocket
┌──────────┴───────────────────┐
│ React frontend (Vite)        │
│ chat · goals/plans ·         │
│ approvals · suggestions ·    │
│ episode browser              │
└──────────────────────────────┘
```

## Autonomy modes (per goal)

| mode     | reads | mutations |
|----------|-------|-----------|
| `approve`| auto  | wait for your approval |
| `tiered` | auto  | wait for your approval |
| `auto`   | auto  | run unattended |

Switch modes live from the plan card while a plan is running; the executor
re-reads the mode before every step. Approvals and rejections are recorded as
feedback episodes and update the learned weights.

## Episodic memory

Every goal, plan, step result, conversation turn and feedback decision is an
append-only episode (`data/companion/episodes.jsonl`). Before planning a new
goal the agent retrieves keyword-similar past episodes (`retrieve()`) and
injects them into the planner prompt, so it remembers what it did last time
and what worked.

## Reinforcement loops

- **Approvals / suggestions**: accept/reject updates smoothed per-kind weights
  (`policy.json`, Laplace over a 40-event window). Kinds you keep rejecting
  get demoted and surface less; the planner sees hints like "tools the
  researcher's workflow favors".
- **Tool outcomes**: every step's success/failure feeds per-tool weights.
- The main app's own loop is reused where possible: low-rated notes are
  re-analyzed by `improve.run` with your criticism injected as prompt hints.

## Proactive engine

A background cycle (default every 300s, or "scan now" in the header) gathers
signals through the live API:

- papers without analysis notes → suggest `notes.refresh_all`
- poor rating trend → suggest `improve.run`
- watch-pool backlog → suggest `pool.import_topic`
- quiet vault → suggest `digest.daily`

Each suggestion is scored `signal_strength × learned_acceptance_weight` and
shown in the feed; accepting turns it into a one-step goal under your chosen
autonomy mode.

## Run

### Reaching the GUI

- Direct: `http://localhost:8001`
- From the main dashboard: the sidebar **Companion** button (robot icon), or
  open `http://localhost:7777/companion` — it 302-redirects to the GUI.
  Set `COMPANION_URL` on the main server to override the target
  (e.g. when the companion runs on another host/port).

### Dev

```bash
# terminal 1 — backend (needs the main server on :7777)
pip install -r companion/backend/requirements.txt
python -m uvicorn hive_companion.main:app --port 8001 --app-dir companion/backend

# terminal 2 — frontend with hot reload
cd companion/frontend && npm install && npm run dev   # http://localhost:5173
```

### Production / Docker

```bash
npm --prefix companion/frontend install
docker compose up -d --build   # adds the `companion` service → http://localhost:8001
```

Environment knobs: `HIVE_API_URL`, `HIVE_TOKEN` (same token as the main
server), `COMPANION_DATA_DIR`, `COMPANION_PROACTIVE_INTERVAL`,
`COMPANION_APPROVAL_TIMEOUT`, `OLLAMA_BASE_URL`, `OLLAMA_FAST_MODEL`.

If Ollama is unreachable the planner degrades to deterministic heuristics that
cover common goal shapes (survey / ingest / improve / rebuild / digest).

## Tests

```bash
cd companion/backend && python -m unittest discover -v
```

## Layout

- `companion/backend/hive_companion/` — FastAPI app + agent modules:
  `planner.py`, `executor.py` (approval gates), `episodic.py`, `policy.py`,
  `proactive.py`, `tools.py` (tool registry over the main API), `autonomy.py`.
- `companion/frontend/src/` — React UI: chat, goals & plans, approval inbox,
  suggestion feed, episode browser.
