# Export & Backup

Export your papers and knowledge graph for sharing, backup, or import into other tools.

## CLI

```bash
# BibTeX
python -m hive_research export --bibtex papers.bib

# JSON graph dump
python -m hive_research export --json graph.json

# CSV for spreadsheets
python -m hive_research export --csv papers.csv

# Full backup (ZIP)
python -m hive_research export --backup backup.zip
python -m hive_research export --backup backup.zip --no-pdfs  # exclude PDFs
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/export/bibtex` | GET | Download BibTeX file |
| `/api/export/json` | GET | Download graph JSON |
| `/api/export/csv` | GET | Download papers CSV |
| `/api/export/backup` | GET | Download backup ZIP |

## Python Client

```python
from hive_research import HiveClient

client = HiveClient("http://localhost:7777")

bibtex = client.export_bibtex()
json_data = client.export_json()
csv = client.export_csv()
client.create_backup("hive-backup.zip", include_pdfs=False)
```

## Backup Contents

A ZIP backup includes:
- `graph/main.json` — Knowledge graph
- `vault/` — All markdown notes and figures
- `rag/index.json` + `rag/embeddings.npy` — RAG index
- `pool/pool.db` — Research pool data
- `config.yaml` — Configuration
- `papers/*.pdf` — PDFs (optional, excluded by `--no-pdfs`)
