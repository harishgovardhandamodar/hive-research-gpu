# Configuration

Hive Research GPU uses `config.yaml` for persistent settings with environment variable overrides for Hive Serving and Ollama parameters. By default, it looks for `config.yaml` in the current working directory.

## Full Reference

```yaml
# ── Directories ──
directories:
  root: ./data              # Top-level data directory
  papers: ./data/papers     # Downloaded PDF storage
  graph: ./data/graph       # Knowledge graph JSON files
  vault: ./data/vault       # Markdown notes per paper

# ── arXiv Settings ──
arxiv:
  download_pdf: true        # Download PDF after fetching metadata
  max_results: 10           # Default result count for searches

# ── Hive Serving Settings ──
hive:
  base_url: http://localhost:8081    # Hive Server endpoint (hive-server-go)

# ── Ollama LLM Settings ──
ollama:
  base_url: http://localhost:11434   # Ollama API endpoint (used by Hive Server internally)
  model: qwen3.6:35b-mlx            # Main analysis model
  fast_model: llama3.2:3b           # Fast model for tags
  embed_model: nomic-embed-text     # Embedding model
  max_tokens: 16384                 # Max generation tokens
  temperature: 0.1                  # Generation temperature

# ── GPU Settings ──
gpu:
  enabled: true              # Enable GPU acceleration
  device_count: 2            # Number of NVIDIA GPUs
  memory_fraction: 0.95      # Max memory usage per GPU
  parallel_papers: 2         # Concurrent paper processing

# ── Graph Settings ──
graph:
  similarity_threshold: 0.85  # Fuzzy concept match threshold (Jaccard)

# ── RAG Settings ──
rag:
  chunk_size: 512            # Words per chunk
  chunk_overlap: 64          # Overlap between consecutive chunks
  top_k: 5                   # Default number of results to retrieve

# ── Server Settings ──
server:
  host: 0.0.0.0
  port: 7777
```

## Model Resolution

The `Config.resolve_model()` method maps user-facing model aliases to actual model names:

| Input | Returns |
|-------|---------|
| `None` or `""` or `"large"` | `ollama.model` (the main analysis model) |
| `"fast"` | `ollama.fast_model` (the lightweight tag model) |
| any other string | The string itself (raw model name passthrough) |

This is used by all API endpoints (`model` parameter) and the `--model` CLI flag to accept both aliases and explicit model names.

## Environment Variables

| Variable | Overrides | Default |
|----------|-----------|---------|
| `HIVE_BASE_URL` | `hive.base_url` | `http://localhost:8081` |
| `OLLAMA_MODEL` | `ollama.model` | `llama3.2:3b` |
| `OLLAMA_FAST_MODEL` | `ollama.fast_model` | `llama3.2:3b` |
| `OLLAMA_EMBED_MODEL` | `ollama.embed_model` | `nomic-embed-text` |

## Multiple Config Files

The `Config` class accepts a path parameter:

```python
from hive_research.config import Config
cfg = Config("path/to/config.yaml")
```

Config files are parsed with `PyYAML`. Missing keys fall back to defaults specified in `config.py`.
