# GPU Management

## Overview

`GPUManager` provides NVIDIA GPU monitoring and orchestrates Ollama instances across multiple GPUs for parallel LLM inference and embedding.

## Monitoring

Every 5 seconds, a background thread runs `nvidia-smi` to collect:

```
--query-gpu=index,name,memory.total,memory.used,memory.free,
              utilization.gpu,temperature.gpu,power.draw,compute_cap
```

Data is stored in `GPUDevice` dataclass instances accessible via:

```python
gpu_mgr.get_devices()      # → list[GPUDevice]
gpu_mgr.get_device(0)      # → GPUDevice for GPU 0
gpu_mgr.get_status()       # → dict with all device info
```

## GPU Assignment

Two round-robin counters track GPU allocation:

- `get_next_llm_gpu()` — For LLM generation tasks (analysis, chat, RAG answer)
- `get_next_embed_gpu()` — For embedding tasks

This spreads workload evenly across available GPUs.

## Ollama Instance Lifecycle

For dual-GPU setups, `launch_ollama_instances()` starts one Ollama server per GPU:

```
GPU 0 → CUDA_VISIBLE_DEVICES=0 → Ollama on port 11434
GPU 1 → CUDA_VISIBLE_DEVICES=1 → Ollama on port 11435
```

Each instance has:
- `OLLAMA_KEEP_ALIVE=24h` — Models stay loaded
- `OLLAMA_NUM_PARALLEL=4` — Concurrent requests per instance
- `OLLAMA_MAX_LOADED_MODELS=2` — Model slots per instance

If an instance is already running on the target port, it is detected and left untouched.

## Parallelism

The system leverages multiple GPUs in several ways:

| Operation | Parallelism Strategy |
|-----------|---------------------|
| Paper ingestion | One GPU per paper, thread pool up to `parallel_papers` |
| Chunk embedding | Round-robin chunks across GPUs, concurrent threads |
| LLM generation | Round-robin across GPUs per request |
| `generate_parallel()` | Concurrent threads, one GPU per prompt |

## CUDA Device Management

For direct CUDA operations:

```python
gpu_mgr.set_cuda_device(0)  # Sets CUDA_VISIBLE_DEVICES=0
```

## Fallback

When no NVIDIA GPU is detected (`nvidia-smi` not found or returns error), the system operates in CPU-only mode. All LLM and embedding requests go to the single Ollama instance at `base_url`.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/gpu` | GET | GPU status (CUDA or nvidia-smi) |
| `/api/ollama` | GET | Ollama connection status and model availability |

## Configuration

```yaml
gpu:
  enabled: true
  device_count: 2
  memory_fraction: 0.95
  parallel_papers: 2
  embedding_device: 0
  llm_device: 1
```
