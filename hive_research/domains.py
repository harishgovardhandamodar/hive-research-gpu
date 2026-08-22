"""Curated research-domain presets for the Hive Research companion.

Each preset bundles arXiv queries tuned for a research field so the
Research Pool can monitor it out of the box. Presets are the default
seed source for pool topics and can be enabled selectively via
``workflow.domain_presets`` in config.yaml.
"""

from __future__ import annotations

from typing import Any

DOMAIN_PRESETS: list[dict[str, Any]] = [
    {
        "id": "agents",
        "name": "LLM Agents",
        "description": "Autonomous LLM agents: tool use, planning, memory, reasoning loops.",
        "icon": "robot",
        "queries": [
            "LLM agent tool use planning",
            "autonomous agents large language model",
            "agent memory reasoning",
        ],
        "topics": [
            {"name": "LLM agents", "query": "large language model agents tool use"},
            {"name": "Agent planning", "query": "language agent planning reasoning"},
            {"name": "Agent memory", "query": "agent memory experience reuse"},
        ],
    },
    {
        "id": "multiagent",
        "name": "Multi-Agent Systems",
        "description": "Cooperative and competitive multi-agent LLM frameworks, debate, role-play.",
        "icon": "users",
        "queries": [
            "multi-agent collaboration large language models",
            "multi-agent debate framework",
            "cooperative multi-agent reinforcement learning communication",
        ],
        "topics": [
            {"name": "Multi-agent LLM", "query": "multi-agent large language model framework"},
            {"name": "Agent debate", "query": "multi-agent debate reasoning"},
            {"name": "MARL", "query": "multi-agent reinforcement learning cooperation"},
        ],
    },
    {
        "id": "swarms",
        "name": "Agent Swarms",
        "description": "Swarm intelligence, collective behavior, emergent coordination at scale.",
        "icon": "network",
        "queries": [
            "swarm intelligence agents collective",
            "emergent communication population of agents",
            "collective intelligence LLM swarm",
        ],
        "topics": [
            {"name": "Agent swarms", "query": "swarm of language agents collective intelligence"},
            {"name": "Emergent communication", "query": "emergent communication multi-agent"},
        ],
    },
    {
        "id": "alignment",
        "name": "AI Alignment",
        "description": "Value alignment, RLHF, scalable oversight, reward modeling, interpretability.",
        "icon": "compass",
        "queries": [
            "AI alignment value learning",
            "reinforcement learning from human feedback RLHF",
            "scalable oversight reward model interpretability",
        ],
        "topics": [
            {"name": "AI alignment", "query": "AI alignment safety"},
            {"name": "RLHF & oversight", "query": "RLHF scalable oversight reward model"},
            {"name": "Interpretability", "query": "mechanistic interpretability neural networks"},
        ],
    },
    {
        "id": "llm-security",
        "name": "LLM Security",
        "description": "Jailbreaks, prompt injection, backdoors, data poisoning, red-teaming.",
        "icon": "shield",
        "queries": [
            "jailbreak prompt injection large language model",
            "backdoor poisoning attacks language models",
            "red teaming safety evaluation LLM",
        ],
        "topics": [
            {"name": "Prompt injection", "query": "prompt injection attack defense"},
            {"name": "Jailbreaks", "query": "jailbreak LLM safety alignment attack"},
            {"name": "Backdoors & poisoning", "query": "backdoor attack data poisoning"},
        ],
    },
    {
        "id": "agentic-security",
        "name": "Agentic Security",
        "description": "Security of autonomous agents: sandboxing, permissioning, malicious tool use.",
        "icon": "lock",
        "queries": [
            "security risks autonomous agents tool use",
            "sandboxing code executing agents",
            "indirect prompt injection agent environment",
        ],
        "topics": [
            {"name": "Agent security", "query": "safety security autonomous LLM agents"},
            {"name": "Indirect injection", "query": "indirect prompt injection tools web agents"},
        ],
    },
]

_PRESET_INDEX = {p["id"]: p for p in DOMAIN_PRESETS}


def list_domains() -> list[dict[str, Any]]:
    """All presets as light dicts (no topic expansion)."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "icon": p.get("icon", ""),
            "topic_count": len(p.get("topics", [])),
        }
        for p in DOMAIN_PRESETS
    ]


def get_domain(domain_id: str) -> dict[str, Any] | None:
    return _PRESET_INDEX.get(domain_id)


def topics_for_domain(domain_id: str) -> list[dict[str, str]]:
    preset = get_domain(domain_id)
    if not preset:
        return []
    return [dict(t) for t in preset.get("topics", [])]


def all_topics() -> list[dict[str, str]]:
    """Union of every preset's topics (used to seed new pools)."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for p in DOMAIN_PRESETS:
        for t in p.get("topics", []):
            if t["name"] not in seen:
                seen.add(t["name"])
                out.append(dict(t))
    return out


def validate_presets() -> list[str]:
    """Return a list of structural problems; empty means presets are sane."""
    problems: list[str] = []
    ids = [p["id"] for p in DOMAIN_PRESETS]
    if len(ids) != len(set(ids)):
        problems.append("duplicate preset ids")
    for p in DOMAIN_PRESETS:
        if not p.get("name"):
            problems.append(f"{p['id']}: missing name")
        if not p.get("topics"):
            problems.append(f"{p['id']}: no topics")
        for t in p.get("topics", []):
            if not t.get("query", "").strip():
                problems.append(f"{p['id']}: topic '{t.get('name')}' has empty query")
    return problems
