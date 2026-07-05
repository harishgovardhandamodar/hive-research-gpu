# Web Dashboard

The dashboard is a single-page application served by the HTTP server at the root URL. It communicates with the backend via a REST API.

```
python -m hive_research serve --host 0.0.0.0 --port 7777
# → http://localhost:7777
```

## Panels

### Pool

The research pool observatory. Displays papers discovered by automated topic monitoring.

- **Browse** — Papers grouped by topic; each card shows title, authors, abstract snippet
- **New** badge for papers first seen within the last 24 hours
- **Import** button to add individual papers to your knowledge graph
- **Select all** + batch import workflow
- **Graph** — Force-directed visualization of pool papers with Jaccard similarity edges (≥ 0.12)
- **Settings** — Add/remove topics with custom arXiv queries

### Graph

Interactive force-directed knowledge graph.

- D3.js force simulation with drag, pan, zoom
- Color-coded nodes: blue = paper, purple = concept, teal = lineage, orange = web
- Green edges = citation links (`cites`)
- **Filter** — Type to highlight matching nodes
- **Click** any node → preview panel with title, authors, abstract, and actions
- **Refresh** — Regenerate notes for papers missing them
- **Fill Definitions** — Auto-generate concept definitions from context
- **Customization gear** → adjust node colors, sizes, edge colors per type

### Import

Three sub-tabs for adding content:

1. **Paper** — Enter arXiv ID or full URL to add a paper
2. **Web Link** — Enter a blog/article URL to ingest as a web node
3. **Search** — Search arXiv by keyword, preview results, import individually or as batch

### Browse

Full paper library browser:

- **Left panel** — Searchable paper list with lineage/extra badges
- **Right panel** — Paper detail including:
  - File groups: vault notes, experiment files, figures
  - Citation lineage display
  - Markdown preview of any file
  - **Recreate Notes** button to re-run LLM analysis
  - Model selector for refresh operations

### Similarity

Pairwise paper similarity computation:

- Search and select specific papers, or compute over the full library
- Algorithm selector: Combined, Abstract Jaccard, Author Overlap, Concept Overlap
- Results in list view (sorted by score) or matrix view
- Each result shows score with color coding (high/medium/low)

### Chat

RAG question-answering interface:

- Ask questions in natural language
- System retrieves relevant chunks via cosine similarity
- LLM generates answer with `[1]`, `[2]` source citations
- Sources link back to arXiv

### About

System information:

- Paper/concept/edge/chunk counts (stat cards)
- Platform info (OS, Python version)
- Ollama connection status and model availability
- GPU status with per-device memory, utilization, temperature

## Activity Log

Collapsible bottom bar displaying real-time application logs with filter toggles for Info/Done/Warn/Error levels.
