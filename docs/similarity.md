# Similarity

The similarity module computes pairwise similarity between papers in the knowledge graph, using one of four algorithms.

## Algorithms

### Combined (default)

Weighted combination of three signals:

```
score = 0.4 × author_overlap + 0.4 × abstract_sim + 0.2 × edge_score
```

- **Author overlap** — Jaccard similarity of author name sets
- **Abstract similarity** — Token Jaccard similarity of abstracts
- **Edge score** — Number of shared edges (max 5) normalized to [0, 1]

### Abstract Jaccard

Pure token overlap between paper abstracts:

```python
def jaccard_tokens(a, b):
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    return len(ta & tb) / len(ta | tb)
```

### Author Overlap

Ratio of shared authors to total unique authors across both papers.

### Concept Overlap

Overlap of knowledge graph concepts connected to each paper:

```python
shared_concepts / union_of_concepts
```

## Usage

### CLI

```bash
python -m hive_research similarity
```

### API

```bash
GET /api/similarity?algorithm=combined
POST /api/similarity {"paper_ids": ["1706.03762", "2106.09685"], "algorithm": "abstract"}
```

### Python

```python
from hive_research.similarity import paper_similarity_matrix
results = paper_similarity_matrix(kg, algorithm="combined")
```

## Results

Each result contains:

```json
{
  "source": "1706.03762",
  "source_title": "Attention Is All You Need",
  "target": "2106.09685",
  "target_title": "LoRA: Low-Rank Adaptation of Large Language Models",
  "score": 0.1234,
  "author_overlap": 0.0,
  "abstract_sim": 0.0891
}
```

Results are sorted by score descending.
