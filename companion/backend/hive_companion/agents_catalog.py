"""Agent collection catalog — curated from ai-scientist.md (masamasa59/ai-agent-papers).

Three tracks mirroring the survey structure:
- ideation      — Idea Generation & Hypothesis
- experimentation — Experimentation & Discovery
- writing       — Paper Writing & Peer Review

Each entry is a selectable research agent. `implemented=True` means the
companion already ships a concrete toolchain for it (IDEAgent, Deep
Ideation, etc.); the rest are prompt/workflow profiles the planner can
use to shape its tool-call sequence.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentDef:
    id: str
    name: str
    category: str  # ideation | experimentation | writing
    tagline: str
    description: str
    paper_title: str
    paper_url: str
    arxiv_id: str | None
    capabilities: list[str]
    workflow: list[str]
    icon: str
    color: str
    implemented: bool
    autonomy: str  # recommended autonomy mode
    tags: list[str]


CATALOG: list[AgentDef] = [
    # ── Idea Generation & Hypothesis ──────────────────────────────────────
    AgentDef(
        id="research-agent",
        name="ResearchAgent",
        category="ideation",
        tagline="Iterative idea generation over literature",
        description="Iteratively reads related papers, drafts ideas, critiques them and refines — grounded in citation-graph expansion.",
        paper_title="ResearchAgent: Iterative Research Idea Generation over Scientific Literature with LLMs",
        paper_url="https://arxiv.org/abs/2404.07738",
        arxiv_id="2404.07738",
        capabilities=["literature grounding", "iterative refinement", "citation expansion"],
        workflow=["survey related work", "draft seed ideas", "self-critique & revise", "rank by novelty"],
        icon="💡",
        color="#f0b429",
        implemented=False,
        autonomy="tiered",
        tags=["survey-heavy", "grounded"],
    ),
    AgentDef(
        id="chain-of-ideas",
        name="Chain of Ideas",
        category="ideation",
        tagline="Novel ideas via idea chaining",
        description="Chains prior ideas and literature anchors into branching idea paths, then consolidates the most promising chain.",
        paper_title="Chain of Ideas: Revolutionizing Research in Novel Idea Development with LLM Agents",
        paper_url="https://arxiv.org/abs/2410.13185",
        arxiv_id="2410.13185",
        capabilities=["idea chaining", "branching search", "consolidation"],
        workflow=["anchor on seed papers", "branch idea chains", "prune weak branches", "consolidate"],
        icon="⛓",
        color="#f0b429",
        implemented=False,
        autonomy="tiered",
        tags=["creative", "branching"],
    ),
    AgentDef(
        id="biodisco",
        name="BIODISCO",
        category="ideation",
        tagline="Dual-mode evidence hypothesis generation",
        description="Alternates between literature evidence and knowledge-graph evidence, with temporal evaluation of hypothesis plausibility.",
        paper_title="BIODISCO: Multi-agent hypothesis generation with dual-mode evidence",
        paper_url="https://arxiv.org/abs/2508.01285",
        arxiv_id="2508.01285",
        capabilities=["dual evidence", "temporal evaluation", "biomedical"],
        workflow=["collect lit evidence", "collect KG evidence", "synthesize hypotheses", "temporal re-rank"],
        icon="🧬",
        color="#f0b429",
        implemented=False,
        autonomy="tiered",
        tags=["biomedical", "evidence-fusion"],
    ),
    AgentDef(
        id="ideagent",
        name="IDEAgent (QD)",
        category="ideation",
        tagline="Quality-Diversity archive of ideas",
        description="Quality-Diversity search over approach×risk cells; already shipped inside Fox Companion with per-iteration persistence.",
        paper_title="IDEAgent: Agentic Quality-Diversity Search for Research Idea Generation",
        paper_url="https://arxiv.org/abs/2607.22375",
        arxiv_id="2607.22375",
        capabilities=["QD archive", "approach×risk diversity", "built-in"],
        workflow=["map QD cells", "fill archive by novelty", "recombine elites", "export"],
        icon="🗺",
        color="#f0b429",
        implemented=True,
        autonomy="tiered",
        tags=["implemented", "diversity"],
    ),
    AgentDef(
        id="heuresis",
        name="Heuresis",
        category="ideation",
        tagline="Search strategies across quality/diversity/novelty",
        description="Portfolio of search strategies (exploit / explore / novelty-seek) orchestrated by a meta-controller.",
        paper_title="Heuresis: Search Strategies for Autonomous AI Research Agents",
        paper_url="https://arxiv.org/abs/2606.25198",
        arxiv_id="2606.25198",
        capabilities=["portfolio search", "meta-control", "quality-diversity-novelty"],
        workflow=["score ideas on Q/D/N", "select strategy", "generate & evaluate", "adapt portfolio"],
        icon="🧭",
        color="#f0b429",
        implemented=False,
        autonomy="tiered",
        tags=["portfolio", "meta"],
    ),
    # ── Experimentation & Discovery ───────────────────────────────────────
    AgentDef(
        id="ai-scientist",
        name="AI Scientist",
        category="experimentation",
        tagline="Fully automated open-ended discovery",
        description="End-to-end loop: idea → code → experiment → write-up, with automated reviewer feedback loop. The reference agentic scientist.",
        paper_title="The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery",
        paper_url="https://arxiv.org/abs/2408.06292",
        arxiv_id="2408.06292",
        capabilities=["code generation", "experiment execution", "auto write-up", "review loop"],
        workflow=["generate idea", "write & run code", "analyze results", "draft paper & review"],
        icon="🔬",
        color="#3fb27f",
        implemented=False,
        autonomy="auto",
        tags=["end-to-end", "code-first"],
    ),
    AgentDef(
        id="ai-scientist-v2",
        name="AI Scientist-v2",
        category="experimentation",
        tagline="Workshop-level via agentic tree search",
        description="Tree-search over research steps with verifier-guided expansion; reaches workshop-level paper quality.",
        paper_title="The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search",
        paper_url="https://arxiv.org/abs/2504.08066",
        arxiv_id="2504.08066",
        capabilities=["tree search", "verifier guidance", "workshop quality"],
        workflow=["branch hypotheses", "search & verify", "merge best path", "write-up"],
        icon="🌲",
        color="#3fb27f",
        implemented=False,
        autonomy="auto",
        tags=["tree-search", "verification"],
    ),
    AgentDef(
        id="sciagents",
        name="SciAgents",
        category="experimentation",
        tagline="Multi-agent graph reasoning for discovery",
        description="Heterogeneous agents reason over a scientific knowledge graph to propose and validate discoveries.",
        paper_title="SciAgents: Automating Scientific Discovery through Multi-Agent Intelligent Graph Reasoning",
        paper_url="https://arxiv.org/abs/2409.05556",
        arxiv_id="2409.05556",
        capabilities=["KG reasoning", "multi-agent", "graph traversal"],
        workflow=["traverse KG", "propose links", "multi-agent critique", "validate"],
        icon="🕸",
        color="#3fb27f",
        implemented=False,
        autonomy="tiered",
        tags=["knowledge-graph", "multi-agent"],
    ),
    AgentDef(
        id="agent-laboratory",
        name="Agent Laboratory",
        category="experimentation",
        tagline="LLM agents as full ML research assistants",
        description="Covers literature review → data prep → experiment → analysis for ML projects; strong SWE harness.",
        paper_title="Agent Laboratory: Using LLM Agents as Research Assistants",
        paper_url="https://arxiv.org/abs/2501.04227",
        arxiv_id="2501.04227",
        capabilities=["ML pipeline", "data prep", "experiment harness"],
        workflow=["literature review", "prepare data & code", "run experiments", "analyze & report"],
        icon="🧪",
        color="#3fb27f",
        implemented=False,
        autonomy="auto",
        tags=["ml-pipeline", "harness"],
    ),
    AgentDef(
        id="saga",
        name="SAGA",
        category="experimentation",
        tagline="Goal-evolving autonomous agents",
        description="Goals co-evolve with findings; the agent rewrites its objective as evidence accumulates.",
        paper_title="Accelerating Scientific Discovery with Autonomous Goal-evolving Agents (SAGA)",
        paper_url="https://arxiv.org/abs/2512.21782",
        arxiv_id="2512.21782",
        capabilities=["goal evolution", "autonomous", "long-horizon"],
        workflow=["set initial goal", "experiment & observe", "evolve goal", "repeat"],
        icon="🔄",
        color="#3fb27f",
        implemented=False,
        autonomy="auto",
        tags=["goal-evolution", "long-horizon"],
    ),
    # ── Paper Writing & Peer Review ───────────────────────────────────────
    AgentDef(
        id="dolphin",
        name="DOLPHIN",
        category="writing",
        tagline="Closed-loop thinking–practice–feedback",
        description="Loops through thinking, coding practice, and feedback to incrementally improve a research artifact.",
        paper_title="DOLPHIN: Closed-loop Open-ended Auto-research through Thinking, Practice, and Feedback",
        paper_url="https://arxiv.org/abs/2501.03916",
        arxiv_id="2501.03916",
        capabilities=["closed loop", "iterative improvement", "feedback"],
        workflow=["think & plan", "practice (code)", "feedback & revise", "loop"],
        icon="🐬",
        color="#7fb4d4",
        implemented=False,
        autonomy="tiered",
        tags=["closed-loop", "iterative"],
    ),
    AgentDef(
        id="pasa",
        name="PaSa",
        category="writing",
        tagline="Comprehensive paper search agent",
        description="Deep paper search with query expansion, ranking, and de-duplication; ideal pre-step for any survey.",
        paper_title="PaSa: An LLM Agent for Comprehensive Academic Paper Search",
        paper_url="https://arxiv.org/abs/2501.10120",
        arxiv_id="2501.10120",
        capabilities=["paper search", "query expansion", "ranking"],
        workflow=["expand query", "search & retrieve", "rank & dedup", "deliver corpus"],
        icon="🔍",
        color="#7fb4d4",
        implemented=False,
        autonomy="approve",
        tags=["search", "retrieval"],
    ),
    AgentDef(
        id="agentrxiv",
        name="AgentRxiv",
        category="writing",
        tagline="Collaborative autonomous research",
        description="Agents publish preprints to a shared AgentRxiv, read and build on each other's work collaboratively.",
        paper_title="AgentRxiv: Towards Collaborative Autonomous Research",
        paper_url="https://arxiv.org/abs/2503.18102",
        arxiv_id="2503.18102",
        capabilities=["collaboration", "shared preprint", "build-on-others"],
        workflow=["publish draft", "read peers", "extend & cite", "re-publish"],
        icon="🤝",
        color="#7fb4d4",
        implemented=False,
        autonomy="tiered",
        tags=["collaborative", "social"],
    ),
    AgentDef(
        id="scisage",
        name="SciSage",
        category="writing",
        tagline="Multi-agent survey generation",
        description="Crew of agents divides a survey into sections, writes them in parallel, and merges with consistency checks.",
        paper_title="SciSage: A Multi-Agent Framework for High-Quality Scientific Survey Generation",
        paper_url="https://arxiv.org/abs/2506.12689",
        arxiv_id="2506.12689",
        capabilities=["survey writing", "section parallelism", "consistency merge"],
        workflow=["outline sections", "parallel drafting", "cross-check & merge", "polish"],
        icon="📚",
        color="#7fb4d4",
        implemented=False,
        autonomy="tiered",
        tags=["survey", "multi-agent"],
    ),
    AgentDef(
        id="paperbench",
        name="PaperBench / MLR-Bench",
        category="writing",
        tagline="Replication & research evaluation",
        description="Evaluates agents by their ability to replicate papers or conduct open-ended ML research with scoring.",
        paper_title="PaperBench: Evaluating AI's Ability to Replicate AI Research",
        paper_url="https://arxiv.org/abs/2504.01848",
        arxiv_id="2504.01848",
        capabilities=["replication", "evaluation", "benchmarking"],
        workflow=["pick target paper", "replicate code & exps", "evaluate fidelity", "score"],
        icon="⚖",
        color="#7fb4d4",
        implemented=False,
        autonomy="approve",
        tags=["benchmark", "evaluation"],
    ),
]

CATALOG_BY_ID: dict[str, AgentDef] = {a.id: a for a in CATALOG}
CATEGORIES = ["ideation", "experimentation", "writing"]
CATEGORY_LABEL = {
    "ideation": "Idea Generation & Hypothesis",
    "experimentation": "Experimentation & Discovery",
    "writing": "Paper Writing & Peer Review",
}


def catalog_dicts() -> list[dict[str, Any]]:
    return [asdict(a) for a in CATALOG]


# ── selection persistence ─────────────────────────────────────────────────

DEFAULT_SELECTION = ["ideagent", "research-agent", "pasa"]


class AgentSelectionStore:
    """Thread-safe JSON file store for the user's enabled-agent set."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            env_root = os.environ.get("COMPANION_DATA_DIR", "").strip() or os.environ.get(
                "COMPANION_DATA_ROOT", ""
            ).strip()
            if env_root:
                p = Path(env_root)
                path = p / "agent_selection.json" if p.is_dir() or not p.suffix else p
            else:
                base = Path(__file__).resolve().parent.parent.parent
                p = base / "data" / "companion" / "agent_selection.json"
                if not p.parent.exists():
                    p = Path.cwd() / "data" / "companion" / "agent_selection.json"
                path = p
        else:
            p = Path(path)
            if p.suffix != ".json":
                p = p / "agent_selection.json"
            path = p
        self.path = Path(path)
        self._lock = threading.Lock()
        self._selected: set[str] | None = None

    def _load(self) -> set[str]:
        if self._selected is not None:
            return self._selected
        with self._lock:
            if self._selected is not None:
                return self._selected
            if self.path.is_file():
                try:
                    raw = json.loads(self.path.read_text())
                    ids = raw.get("selected_ids") or raw.get("selected") or []
                    valid = {str(x) for x in ids if str(x) in CATALOG_BY_ID}
                    self._selected = valid if valid else set(DEFAULT_SELECTION)
                except Exception:
                    self._selected = set(DEFAULT_SELECTION)
            else:
                self._selected = set(DEFAULT_SELECTION)
            return self._selected

    def get(self) -> list[str]:
        return sorted(self._load())

    def set(self, ids: list[str]) -> list[str]:
        valid = sorted({str(x) for x in ids if str(x) in CATALOG_BY_ID})
        # keep at least one so planner always has context
        if not valid:
            valid = sorted(set(DEFAULT_SELECTION))
        with self._lock:
            self._selected = set(valid)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"selected_ids": valid, "updated_at": time.time()}))
            tmp.replace(self.path)
        return valid

    def is_enabled(self, agent_id: str) -> bool:
        return agent_id in self._load()
