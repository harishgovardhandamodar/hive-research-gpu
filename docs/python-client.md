# Python Client Library

`HiveClient` provides a Pythonic interface to all Hive Research features. It supports two modes:

- **Remote** — Connects to a running Hive server via REST API
- **Embedded** — Directly uses an `Organizer` instance (no server needed)

## Installation

The client is included with `hive-research-gpu`. No additional dependencies required for embedded mode. Remote mode requires `requests`.

## Usage

### Remote Mode

```python
from hive_research import HiveClient

client = HiveClient("http://localhost:7777")

# System
stats = client.stats()
papers = client.papers()

# Add a paper
result = client.add_paper("1706.03762")

# RAG query with hybrid search
answer = client.query("What is attention?", mode="hybrid")
print(answer["answer"])

# Similarity
sim = client.similarity(algorithm="combined", top_k=10)

# Collections
client.create_collection("my-papers")
client.add_to_collection("my-papers", "1706.03762")

# Favorites
client.add_favorite("1706.03762")

# Export
bibtex = client.export_bibtex()
backup = client.create_backup("backup.zip")
```

### Embedded Mode (no server)

```python
from hive_research import HiveClient, Organizer, Config

config = Config()
org = Organizer(config)
client = HiveClient(org=org)

stats = client.stats()
result = client.add_paper("1706.03762")
```

### Authenticated Mode

```python
client = HiveClient("http://localhost:7777", auth_token="your-token-here")
```

## Full API Reference

| Method | Description |
|--------|-------------|
| `stats()` | System statistics |
| `graph()` | Knowledge graph in node-link format |
| `papers()` | List all papers |
| `concepts()` | List all concepts |
| `add_paper(id, model)` | Add paper by arXiv ID |
| `search_arxiv(query)` | Search arXiv (no import) |
| `import_papers(query, model)` | Search and import |
| `ingest_web(url)` | Ingest web URL |
| `query(question, mode)` | RAG question answering |
| `similarity(algorithm, paper_ids, top_k)` | Similarity matrix |
| `list_collections()` | List all collections |
| `create_collection(name, description)` | Create collection |
| `delete_collection(name)` | Delete collection |
| `add_to_collection(collection, paper_id)` | Add paper to collection |
| `remove_from_collection(collection, paper_id)` | Remove paper from collection |
| `get_collection_papers(collection)` | Get papers in collection |
| `list_favorites()` | List favorites |
| `add_favorite(paper_id)` | Add favorite |
| `remove_favorite(paper_id)` | Remove favorite |
| `save_search(query, name)` | Save search |
| `list_saved_searches()` | List saved searches |
| `delete_saved_search(index)` | Delete saved search |
| `export_bibtex()` | Export as BibTeX |
| `export_json()` | Export graph as JSON |
| `export_csv()` | Export papers as CSV |
| `create_backup(path, include_pdfs)` | Create backup ZIP |
