# Docker Deployment

## Prerequisites

- Docker with NVIDIA Container Toolkit (`nvidia-docker2` or `nvidia-container-toolkit`)
- NVIDIA GPU(s) with CUDA 12.4+ drivers
- At least 16GB system RAM (more recommended for LLM inference)

## Quick Start

```bash
docker-compose up --build
```

This will:
1. Build the Hive Server image from `hive-serving-local-Cluster/hive-server-go/Dockerfile`
2. Start the Hive Server on port 8081 (job queue + load balancing for Ollama)
3. Build the Hive Research GPU image from `Dockerfile`
4. Start the web server on port 7777
5. Mount a persistent volume `hive_data` at `/app/data`

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HIVE_BASE_URL` | `http://localhost:8081` | Hive Server endpoint |
| `OLLAMA_MODEL` | `llama3.2:3b` | Main LLM model |
| `OLLAMA_FAST_MODEL` | `llama3.2:3b` | Fast model for tags |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |

### Model Management

Models must be pulled before first use. You can either:

1. Pre-pull in a derived Dockerfile:
```dockerfile
RUN ollama pull qwen3.6:35b-mlx && ollama pull nomic-embed-text
```

2. Pull via exec after container starts:
```bash
docker exec -it hive-research-gpu-hive-research-gpu-1 ollama pull qwen3.6:35b-mlx
```

## docker-compose.yml

```yaml
services:
  hive-server:
    build:
      context: ../hive-serving-local-Cluster
      dockerfile: hive-server-go/Dockerfile
    network_mode: host
    environment:
      - OLLAMA_BASE_URL=http://localhost:11434
      - OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3.6:35b}
      - SERVER_PORT=8081
      - MAX_CONCURRENT=4
      - MAX_CLIENTS=10
      - MESH_ENABLED=false
    restart: unless-stopped

  hive-research-gpu:
    build:
      context: ..
      dockerfile: hive-research-gpu/Dockerfile
    network_mode: host
    volumes:
      - hive_data:/app/data
    environment:
      - HIVE_BASE_URL=http://localhost:8081
      - OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3.6:35b}
      - OLLAMA_FAST_MODEL=${OLLAMA_FAST_MODEL:-llama3.2:3b}
      - OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL:-nomic-embed-text}
    shm_size: 8gb
    restart: unless-stopped
    depends_on:
      - hive-server
```

## Dockerfile Structure

1. Base: `nvidia/cuda:12.4.1-runtime-ubuntu22.04`
2. Python 3.12 in a virtual environment at `/venv`
3. Application code and `hive-datatype` copied into `/app`
4. Environment configured to connect to the Hive Server at `HIVE_BASE_URL`

## Persistent Data

Data is stored in the `hive_data` Docker volume (`/app/data` in the container):

```
/var/lib/docker/volumes/hive_research_gpu_hive_data/
├── papers/       # Downloaded PDFs
├── graph/        # Knowledge graph
├── vault/        # Markdown notes
├── rag/          # RAG index + embeddings
└── pool/         # Research pool database
```

## Health Check

The container includes a health check that hits `/api/stats` every 30 seconds (40s startup grace period, 5 retries).
