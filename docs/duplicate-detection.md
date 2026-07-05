# Duplicate Detection

Detects potential duplicate papers in the knowledge base by comparing title token similarity.

## How it works

When papers are displayed in the Browse tab, the system computes Jaccard token similarity between paper titles. Any pair with similarity ≥ 0.85 (configurable) is flagged as a potential duplicate.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/papers/duplicates?paper_id=X&threshold=0.85` | GET | Find duplicates for a specific paper |
| `/api/papers/duplicates?threshold=0.85` | GET | Find ALL duplicate groups across all papers |

## Response Format

```json
[
  {"paper_id": "2106.09685", "title": "LoRA: Low-Rank Adaptation...", "similarity": 0.91},
  {"paper_id": "2205.14135", "title": "LoraHub: Efficient...", "similarity": 0.87}
]
```

## Dashboard Display

In the Browse tab, papers with potential duplicates show a **⚠ N** badge:
- Yellow warning icon with duplicate count
- Hover shows the titles of duplicate papers
- Badge disappears when duplicates are resolved

## Threshold

The default similarity threshold is 0.85 (85% Jaccard token overlap). You can pass a custom threshold via the API:
`/api/papers/duplicates?threshold=0.7`
