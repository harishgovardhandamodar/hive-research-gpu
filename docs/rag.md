# RAG Engine

The RAG (Retrieval-Augmented Generation) engine indexes paper content and enables semantic search and question answering over your knowledge base.

## Indexing

When a paper is ingested:

1. **Chunking** — PDF text is split into word-level chunks (default: 512 words with 64-word overlap)
2. **Embedding** — Each chunk is embedded using the embedding model (`nomic-embed-text`) via Ollama
3. **Parallel Embedding** — Chunks are distributed across available GPUs for concurrent embedding
4. **Storage** — Index metadata saved as `data/rag/index.json`, dense embeddings as `data/rag/embeddings.npy`

## Search

Cosine similarity between query embedding and all chunk embeddings:

```python
sims = chunk_embeddings @ query_embedding
sims /= (norms(chunks) * norm(query))
```

Results are sorted by similarity score, returning the top-k chunks (default: 5).

## Answer Generation

The `answer()` method:
1. Retrieves top-k chunks
2. Builds a prompt with chunk context and source numbering
3. Calls the LLM with `temperature=0.0` for deterministic answers
4. Returns the answer text plus deduplicated source citations

## Configuration

```yaml
rag:
  chunk_size: 512       # Words per chunk
  chunk_overlap: 64     # Overlap between consecutive chunks
  top_k: 5              # Number of chunks to retrieve
```

## Persistence

The RAG index survives restarts via:
- `data/rag/index.json` — Chunk metadata (text, source_id, source_title, chunk_idx)
- `data/rag/embeddings.npy` — Dense embedding matrix (numpy .npy format)

On startup, both files are loaded into memory for fast similarity search.

## Stats

```python
rag.stats()
# → {"chunks": 450, "dimension": 768, "papers": 12}
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/query` | POST | Ask a question with `{"question": "..."}` |
