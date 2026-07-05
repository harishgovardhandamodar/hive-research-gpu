# Getting Started

## Prerequisites

- Python 3.12+
- [Ollama](https://ollama.ai) installed and running
- NVIDIA GPU(s) with CUDA 12.4+ (optional — falls back to CPU)
- Internet access for arXiv API and PDF downloads

## Step 1: Install Ollama and Pull Models

```bash
# Install Ollama (Linux/macOS)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull required models
ollama pull llama3.2:3b          # Fast model for tag extraction
ollama pull qwen3.6:35b-mlx     # Main model for deep analysis
ollama pull nomic-embed-text     # Embeddings for RAG
```

Ollama's default port is `11434`. For dual-GPU setups, a second instance runs on `11435`.

## Step 2: Install Hive Research GPU

### From PyPI

```bash
pip install hive-research-gpu
```

### From source

```bash
git clone https://github.com/your-org/hive-research-gpu
cd hive-research-gpu
pip install -e .
```

The `hive-datatype` package must be available. The `__init__.py` auto-discovers it at `../hive-datatype/` relative to the project.

## Step 3: Configure

Copy the default `config.yaml` and adjust to your environment:

```bash
cp config.yaml config.local.yaml
# Edit config.local.yaml as needed
```

Key settings:
- `ollama.base_url` — Ollama endpoint (default: `http://localhost:11434`)
- `ollama.model` — Main LLM for paper analysis
- `ollama.fast_model` — Smaller LLM for tag extraction
- `ollama.embed_model` — Embedding model
- `gpu.device_count` — Number of available NVIDIA GPUs
- `gpu.parallel_papers` — Number of papers to process concurrently

Environment variable overrides:
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_FAST_MODEL`
- `OLLAMA_EMBED_MODEL`

## Step 4: Run

### CLI mode

```bash
# Search arXiv
python -m hive_research search "attention mechanism" -n 10

# Add a paper to your knowledge base (uses the large model by default)
python -m hive_research add 1706.03762

# Import papers using the fast model for quicker processing
python -m hive_research import "graph neural networks" -n 5 --model fast

# Check GPU status
python -m hive_research gpu

# Ask a question over your papers
python -m hive_research query "What methods are used for graph classification?"
```

### Web Dashboard

```bash
python -m hive_research serve
# Open http://localhost:7777
```

## Step 5: Add Your First Paper

From the dashboard:

1. Go to the **Import** panel
2. Enter an arXiv ID (e.g. `1706.03762`) or URL
3. Click **Add Paper**
4. The pipeline will: fetch metadata → download PDF → extract text → analyze with LLM → populate graph → write vault notes → index for RAG

Repeat with more papers. The knowledge graph grows automatically, deduplicating concepts and linking related work.

## Programmatic Access (Python Client)

```python
from hive_research import HiveClient

# Remote mode (server must be running)
client = HiveClient("http://localhost:7777")

# Check system status
stats = client.stats()
print(f"Papers: {stats['papers']}, Concepts: {stats['concepts']}")

# Add a paper
result = client.add_paper("1706.03762")
print(result)

# Ask a question
answer = client.query("What methods are used for graph classification?", mode="hybrid")
print(answer["answer"])
```

## Chrome Extension

Install the Chrome extension for one-click web ingestion:

1. Open `chrome://extensions` → Developer mode → Load unpacked
2. Select `chrome-extension/` from the project directory
3. Click the 🐝 icon on any webpage → **Send to Hive Research**
