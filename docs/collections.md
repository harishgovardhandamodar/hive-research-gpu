# Paper Collections & Favorites

Organize papers into named collections, save favorite papers for quick access, and persist search queries for reuse.

## CLI

```bash
# Collections
python -m hive_research collections list
python -m hive_research collections create "transformers" --description "Papers about transformer architectures"
python -m hive_research collections delete "transformers"
python -m hive_research collections add "transformers" 1706.03762
python -m hive_research collections remove "transformers" 1706.03762

# Favorites
python -m hive_research favorites list
python -m hive_research favorites add 1706.03762
python -m hive_research favorites remove 1706.03762
```

## API

### Collections

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/collections` | GET | List all collections |
| `/api/collections/papers?collection=` | GET | Get papers in collection |
| `/api/collections/create` | POST | Create collection `{"name", "description"}` |
| `/api/collections/delete` | POST | Delete collection `{"name"}` |
| `/api/collections/add` | POST | Add paper `{"collection", "paper_id"}` |
| `/api/collections/remove` | POST | Remove paper `{"collection", "paper_id"}` |

### Favorites

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/favorites` | GET | List favorites |
| `/api/favorites/add` | POST | Add favorite `{"paper_id"}` |
| `/api/favorites/remove` | POST | Remove favorite `{"paper_id"}` |

### Saved Searches

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/searches` | GET | List saved searches |
| `/api/searches/save` | POST | Save search `{"query", "name"}` |
| `/api/searches/delete` | POST | Delete search `{"index"}` |

## Storage

Collections are stored as JSON at `data/collections.json`:

```json
{
  "collections": {
    "transformers": {
      "name": "transformers",
      "description": "Papers about transformer architectures",
      "papers": ["1706.03762", "2106.09685"],
      "created": "2025-01-23T...",
      "updated": "2025-01-23T..."
    }
  },
  "favorites": ["1706.03762"],
  "saved_searches": [
    {"name": "GNN", "query": "graph neural networks", "created": "..."}
  ]
}
```
