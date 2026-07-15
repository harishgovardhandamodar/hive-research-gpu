# GPU Management

## Overview

`GPUManager` provides NVIDIA GPU monitoring for observability. Inference routing is handled by the Hive Serving cluster (hive-server-go), which manages job queuing, load balancing, and GPU orchestration.

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

## Parallelism

The system uses the Hive Serving cluster for all inference. The job queue handles concurrency and load balancing internally.

| Operation | Parallelism Strategy |
|-----------|---------------------|
| Paper ingestion | Thread pool up to `parallel_papers` |
| Chunk embedding | Concurrent job submissions to Hive Server |
| LLM generation | Hive Server queue manages concurrency |
| `generate_parallel()` | Concurrent threads submitting Hive jobs |

## CUDA Device Management

For direct CUDA operations:

```python
gpu_mgr.set_cuda_device(0)  # Sets CUDA_VISIBLE_DEVICES=0
```

## Fallback

When no NVIDIA GPU is detected (`nvidia-smi` not found or returns error), the system operates in CPU-only mode. All LLM and embedding requests route through the Hive Server, which forwards to Ollama running on CPU.

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
