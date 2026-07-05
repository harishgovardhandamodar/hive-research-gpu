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
1. Build the Docker image from `Dockerfile`
2. Start two Ollama instances (GPU 0 on port 11434, GPU 1 on port 11435)
3. Start the Hive Research GPU web server on port 7777
4. Mount a persistent volume `hive_data` at `/app/data`

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
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
  hive-research-gpu:
    build:
      context: ..
      dockerfile: hive-research-gpu/Dockerfile
    ports:
      - "7777:7777"
    volumes:
      - hive_data:/app/data
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.2:3b}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 2
              capabilities: [gpu]
    runtime: nvidia
    shm_size: 8gb
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7777/api/stats"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 40s
```

## Dockerfile Structure

1. Base: `nvidia/cuda:12.4.1-runtime-ubuntu22.04`
2. Python 3.12 in a virtual environment at `/venv`
3. Ollama installed via official installer script
4. Application code and `hive-datatype` copied into `/app`
5. `entrypoint.sh` starts both Ollama instances before launching the Python server
6. Non-root user `hive` for security

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
