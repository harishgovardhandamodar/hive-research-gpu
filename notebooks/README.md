# Hive Research GPU — Jupyter Notebooks

A collection of Jupyter notebooks for interacting with the Hive API programmatically.

## Prerequisites

```bash
pip install jupyter pandas matplotlib requests
python -m hive_research serve  # Start the API server
```

## Notebooks

| Notebook | Description |
|----------|-------------|
| `01-quick-start.ipynb` | Check stats, browse papers, add paper, view graph, RAG query |
| `02-knowledge-graph-analysis.ipynb` | Analyze node types, relations, similarity distribution with pandas/matplotlib |
| `03-rag-demo.ipynb` | Compare vector vs hybrid search, ask your own questions |

## Usage

```bash
cd notebooks
jupyter notebook
# Open http://localhost:8888 and select a notebook
```

All notebooks connect to the Hive server at `http://localhost:7777`.
