"""Contracted specialist agents that decompose one paper's analysis.

The pipeline used to ask a single model fifteen questions in one prompt and
write whatever came back. That prompt was long enough to strain context, and —
more importantly — it made every failure indistinguishable. A thin note could
mean the extractor ran out of context, or skipped the ablation, or the model
declined to say, and nothing in the output distinguished those three.

So the work is split along the seams the notes already have. Each seam becomes
its own agent with its own contract, its own prompt and its own context budget:

- ``tag-classifier`` on the fast model over the abstract only, exactly as before
  — tags are a routing concern, not an analysis one.
- ``contribution-extractor`` for what the paper claims.
- ``experiment-analyst`` for what it measured, splitting that from the claims
  because those are the two things a long prompt actually conflates.
- ``concept-extractor`` over a method-weighted context, because concepts live in
  the body and asking for them in an abstract-weighted context returns abstracts'
  topics.
- ``lineage-tracer`` with the graph's existing concepts injected, which is what
  makes "how does this differ" answerable instead of guessed.

The split costs more round trips than one prompt. That is a real trade and it is
made deliberately: each section now has a name attached to its failure, and the
ledger records which role produced what. A verifier then checks extracted numbers
against the source text, which is the one failure mode that matters more than
all the rest combined — a plausible wrong number in a summary.

Three invariants this module holds to:

1. **No role invents closure.** A role that cannot extract records ``failed``
   and contributes nothing. It never writes an empty section that reads as a
   finding about the paper.
2. **Every role's LLM call is on the ledger** with requested and served models
   recorded separately, because the gateway substitutes and a note that claims
   the wrong author is worse than no note.
3. **Agents run sequentially within a paper.** Parallelism in this system is
   across papers (bounded by ``gpu_parallel_papers``); fanning out here too would
   square it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from . import assurance_ledger as al
from . import ledger as lg
from . import swarm as sw
from .ledger import Mandate
from .ledger_models import LedgerStore

logger = logging.getLogger(__name__)

#: Sentinel written into the note when a role produced nothing. Distinct from an
#: empty string so a reader (and the critic) can tell "the role failed" from "the
#: paper says nothing on this".
NOT_PRODUCED = "_not produced_"

_CONFIDENCE_SYSTEM = (
    "You are a precise information extraction system. "
    "Respond ONLY with valid JSON. No markdown, no explanation."
)


@dataclass
class Agent:
    """One contracted extraction role."""

    role: str
    intent: str
    # Kept short on purpose: the section-level instruction is a role
    # specification, and the long-standing practice here is that a chunk of
    # quoted paper text is never safe to follow as an instruction.
    system: str
    build_prompt: Callable[["AgentContext"], str]
    fields: tuple[str, ...] = ()
    max_chars: int = 12000
    # ``true`` means "cheap and independent" and qualifies for the fast model.
    fast: bool = False
    # Section weighting for context selection, when the role needs a different
    # slice of the paper than the default whole-text budget. "method" favours
    # method/experiment sections over abstract/conclusion.
    system_context: Optional[str] = None


@dataclass
class AgentContext:
    """Everything a role may read, and where its work is recorded."""

    run_id: str
    title: str
    text: str
    llm: Any
    config: Any
    figures: list[dict[str, Any]] = field(default_factory=list)
    graph_context: str = ""
    model: Optional[str] = None
    gpu_id: Optional[int] = None
    store: Optional[LedgerStore] = None
    # Model the gateway actually served, per role. Not the same as ``model``:
    # the gateway substitutes, and the note must name the real author.
    served_models: dict[str, str] = field(default_factory=dict)
    requested_models: dict[str, str] = field(default_factory=dict)
    # Hash of the previous role's completed event, for the lineage edge.
    last_event: Optional[str] = None
    llm_calls: int = 0
    budget: dict[str, float] = field(default_factory=dict)
    last_error: Optional[str] = None
    # Values the verifier is asked to adjudicate. Populated by run_verifier just
    # before it calls the verifier role.
    claims: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    role: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    produced: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    error: Optional[str] = None
    event: Optional[str] = None
    served_model: str = ""


# ------------------------------------------------------------- grounding ---

# A number worth checking: has a decimal point or a thousands separator, or is a
# percentage. Bare small integers are excluded on purpose -- "3 layers" is not a
# finding, and checking it produces a stream of false alarms that make the check
# noise.
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+(?:\.\d+)?\s*%")
_EVIDENCE_FIELDS = ("summary", "tldr", "notes", "limitations", "lineage_notes",
                    "main_findings", "results", "methodology", "dataset")


def _numbers_in(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers_in(v, out)
    elif isinstance(value, (int, float)):
        out.add(str(value))
    elif isinstance(value, str):
        for m in _NUMBER.findall(value):
            out.add(m.strip())


def _norm_number(token: str) -> list[str]:
    """Every spelling of a number we might find in PDF-extracted text.

    PDF text extraction is inconsistent about thousands separators, so "1,024"
    may appear in the paper as "1024" and vice versa. Both are accepted; a
    percent sign and a bare decimal are also cross-checked, because a model that
    says "95.2" for a table cell reading "95.2%" is grounded, not inventing.
    """
    t = token.strip().rstrip("%").strip()
    cands = [t, t.replace(",", "")]
    try:
        f = float(t.replace(",", ""))
        cands += [str(f), f"{f:g}"]
        if f.is_integer():
            cands.append(str(int(f)))
            cands.append(f"{int(f):,}")
    except ValueError:
        pass
    return [c for c in dict.fromkeys(cands) if c]


# ------------------------------------------------------- context selection --

#: Heading words that carry a role's subject matter, and how much each is worth
#: when that role's budget is limited. Mirrors the pipeline's own section
#: priority, narrowed to the two slices the swarm needs.
_CONTEXT_HINTS: dict[str, tuple[tuple[str, int], ...]] = {
    "method": (("method", 3), ("approach", 3), ("model", 2), ("architecture", 2),
               ("experiment", 3), ("evaluation", 3), ("setup", 2), ("result", 2),
               ("ablation", 2), ("abstract", 1), ("introduction", 1)),
}


def _context_for(agent: Agent, text: str) -> str:
    """The slice of the paper one role gets.

    Two knobs. ``max_chars`` bounds every role, which matters more now than it
    did with one prompt: five roles reading the same 12k characters is five times
    the prefill cost. ``system_context`` re-orders blocks first for the roles
    whose subject matter is not at the front of the paper — concepts are defined
    in the body, so an abstract-weighted slice returns the paper's topic labels
    instead of its vocabulary.

    Selection works on blank-line blocks, not parsed headings. The heading
    parser treats any all-caps line as a heading, so a method section whose body
    is upper-case (a constant, an acronym table) is mis-split and its text lands
    under a heading that scores zero -- dropping exactly the content this role
    was pointed at. Scoring blocks directly cannot lose it that way.
    """
    if len(text) <= agent.max_chars:
        return text
    hints = _CONTEXT_HINTS.get(agent.system_context or "")
    if not hints:
        return text[:agent.max_chars]

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) < 2:
        return text[:agent.max_chars]

    def score(block: str) -> int:
        low = block.lower()
        return sum(w for needle, w in hints if needle in low)

    ranked = sorted(((score(b), i, b) for i, b in enumerate(blocks)),
                    key=lambda t: (-t[0], t[1]))
    out: list[str] = []
    budget = agent.max_chars
    for sc, _, block in ranked:
        if sc == 0:
            continue
        take = min(len(block), budget)
        if take < 60:
            continue
        out.append(block[:take])
        budget -= take
        if budget <= 0:
            break
    return "\n\n".join(out) if out else text[:agent.max_chars]


def verify_grounding(text: str, analysis: dict[str, Any],
                     claimed: Optional[list[str]] = None) -> dict[str, Any]:
    """Check that numbers in the analysis appear in the source text.

    A substring check, and deliberately a weak one — it cannot tell a paper's own
    number from one the model shifted. It catches the case that matters, which is
    a number with no basis in the text at all.

    The ratio is reported, not enforced at warn level: an unfaithful paraphrase
    trips a substring check, and a gate that cries wolf on honest work is a gate
    people route around.
    """
    haystack = re.sub(r"\s+", " ", text or "")
    found = set(claimed or ())
    if not found:
        for fieldname in _EVIDENCE_FIELDS:
            _numbers_in(analysis.get(fieldname), found)
    supported: list[str] = []
    ungrounded: list[str] = []
    for token in sorted(found):
        variants = _norm_number(token)
        if any(v in haystack for v in variants):
            supported.append(token)
        else:
            ungrounded.append(token)
    total = len(supported) + len(ungrounded)
    return {
        "verdict": "supported" if total and not ungrounded
                   else ("unverified" if total else "unverified"),
        "checked": len(found),
        "supported": supported,
        "ungrounded": ungrounded,
        "grounded_ratio": (len(supported) / total) if total else None,
        "note": ("A substring check, not semantic verification: it catches a "
                 "number with no basis in the source, not a subtly wrong one."),
    }


# ---------------------------------------------------------------- prompts ---

def _numbered(text: str) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(text.split("\n"), 1))


def _paper_header(ctx: AgentContext, body: str) -> str:
    return f"Title: {ctx.title}\n\n{body}"


def _tags_prompt(ctx: AgentContext) -> str:
    return (f"Paper: {ctx.title}\n\n"
            f"{ctx.text[:2000]}\n\n"
            'Extract up to 5 key tags (short keywords) as a JSON list: {"tags": [...]}')


def _contributions_prompt(ctx: AgentContext) -> str:
    fig = _figure_reference(ctx.figures)
    return _paper_header(ctx, f"{fig}{ctx.text}\n\n"
        "Return ONLY valid JSON with these fields:\n"
        "{\n"
        '  "summary": "2-3 sentence summary covering problem, approach, and key results (include numbers)",\n'
        '  "tldr": "One-sentence takeaway a researcher can quote",\n'
        '  "notes": "Detailed explanation of the method, architecture, and results with specific numbers",\n'
        '  "limitations": "Weaknesses, failure cases, assumptions that may not hold, and open questions"\n'
        "}")


def _experiments_prompt(ctx: AgentContext) -> str:
    return _paper_header(ctx, f"{ctx.text}\n\n"
        "Return ONLY valid JSON with these fields:\n"
        "{\n"
        '  "experiments": [\n'
        "    {\n"
        '      "name": "Experiment name",\n'
        '      "goal": "What this tests",\n'
        '      "methodology": "Method used",\n'
        '      "dataset": "Dataset name",\n'
        '      "setup": "Hyperparameters, dimensions",\n'
        '      "baselines": "Methods compared against",\n'
        '      "metrics": {"metric_name": "value"},\n'
        '      "results": "Key results with numbers",\n'
        '      "findings": "Key takeaways"\n'
        "    }\n"
        "  ],\n"
        '  "experiment": {"methodology": "...", "dataset": "...", "setup": "..."},\n'
        '  "results": {"main_findings": "...", "metrics": {"metric_name": "value"}},\n'
        '  "reproduction": {\n'
        '    "datasets": ["dataset names used"],\n'
        '    "hyperparameters": "key hyperparameters needed to reproduce",\n'
        '    "metrics": ["evaluation metrics"],\n'
        '    "compute": "hardware/training time if stated",\n'
        '    "code_url": "official code repository URL if mentioned"\n'
        "  },\n"
        '  "experiment_ideas": ["1-3 concrete follow-up experiment ideas building on this paper"]\n'
        "}")


def _concepts_prompt(ctx: AgentContext) -> str:
    return _paper_header(ctx, f"{ctx.text}\n\n"
        "Return ONLY valid JSON with these fields:\n"
        "{\n"
        '  "concepts": [{"name": "...", "definition": "...", "relation": "type"}],\n'
        '  "relations": [{"source": "...", "target": "...", "relation": "..."}]\n'
        "}\n"
        "Use only technical concepts the paper itself defines or relies on. "
        "Do not invent relations between concepts that are not linked.")


def _lineage_prompt(ctx: AgentContext) -> str:
    known = (f"\n\nConcepts already in this knowledge graph:\n{ctx.graph_context}\n"
             if ctx.graph_context else
             "\n\nNo related work is already indexed in this graph.\n")
    return _paper_header(ctx, f"{ctx.text}\n{known}\n"
        "Return ONLY valid JSON:\n"
        '{\n'
        '  "lineage_notes": "Prior work this builds on and how it differs. '
        'If the paper does not state its relationship to prior work, say so '
        'explicitly rather than guessing at citations."\n'
        "}")


def _verifier_prompt(ctx: AgentContext) -> str:
    return _paper_header(ctx, f"{ctx.text}\n\n"
        "These values were extracted from the paper by another system. For each, "
        "decide whether it appears in the text above.\n\n"
        f"{_numbered(chr(10).join(ctx.claims or []))}\n\n"
        "Return ONLY valid JSON:\n"
        '{\n'
        '  "verdicts": [{"claim": "the value", "verdict": "supported|unsupported|uncertain", '
        '"note": "why, briefly"}]\n'
        "}")


def _figure_reference(figures: list[dict[str, Any]]) -> str:
    """Figure placeholders the model is asked to cite, resolved later to files.

    The parser emits ``[FIGURE:page=N]`` markers; the note writer turns them into
    image links. This is where the model is told they exist.
    """
    if not figures:
        return ""
    lines = [f"[FIGURE:page={f.get('page')}]"
             f"{(f.get('caption') or '').strip()}" for f in figures]
    return ("Figures available in this paper:\n"
            + "\n".join(lines) + "\n\n")


EXTRACTION_AGENTS: tuple[Agent, ...] = (
    Agent(
        role="tag-classifier", intent="classify_tags", fast=True,
        system=_CONFIDENCE_SYSTEM, max_chars=2000,
        build_prompt=_tags_prompt, fields=("tags",),
    ),
    Agent(
        role="contribution-extractor", intent="extract_contributions",
        system=_CONFIDENCE_SYSTEM,
        build_prompt=_contributions_prompt,
        fields=("summary", "tldr", "notes", "limitations"),
    ),
    Agent(
        role="experiment-analyst", intent="analyze_experiments",
        system=_CONFIDENCE_SYSTEM,
        build_prompt=_experiments_prompt,
        fields=("experiment", "experiments", "results", "reproduction",
                "experiment_ideas"),
    ),
    Agent(
        role="concept-extractor", intent="extract_concepts",
        system=_CONFIDENCE_SYSTEM,
        # Method and experiments weighted above abstract/conclusion: concepts are
        # defined in the body, and an abstract-weighted context returns the
        # paper's topic labels instead of its technical vocabulary.
        system_context="method",
        max_chars=10000,
        build_prompt=_concepts_prompt,
        fields=("concepts", "relations"),
    ),
    Agent(
        role="lineage-tracer", intent="trace_lineage",
        system=_CONFIDENCE_SYSTEM,
        build_prompt=_lineage_prompt, fields=("lineage_notes",),
    ),
)

#: The LLM-backed verifier. Separate from :data:`EXTRACTION_AGENTS` because it
#: consumes the others' output rather than the source, and runs after them.
VERIFIER_AGENT = Agent(
    role="verifier", intent="verify_claims",
    system=_CONFIDENCE_SYSTEM,
    build_prompt=_verifier_prompt, fields=("verdicts",),
)


# ------------------------------------------------------------- execution ---

def _contract_inputs(ctx: AgentContext) -> dict[str, Any]:
    return {
        "text": ctx.text, "title": ctx.title, "figures": ctx.figures,
        "graph_context": ctx.graph_context, "analysis": {}, "claims": ctx.claims,
    }


def _confidence_for(agent: Agent, data: dict[str, Any]) -> float:
    """Share of the role's declared fields that produced a value.

    A role that filled two of four fields is not half as trustworthy, it is a role
    with two honest gaps -- so this is a completeness signal, and the ledger
    records the missing field names next to it. The number exists so a hand-off
    can be *gated* on it, which is the actual requirement.
    """
    if not agent.fields:
        return 1.0
    got = sum(1 for f in agent.fields if data.get(f) not in (None, "", [], {}))
    return round(got / len(agent.fields), 2)


def run_agent(agent: Agent, ctx: AgentContext,
              record_lifecycle: bool = True) -> AgentResult:
    """Run one contracted role: check, spawn, call, record, settle.

    Every exit path writes an event. A role that dies without one is exactly the
    "silent absence" this whole layer exists to rule out.

    ``record_lifecycle=False`` keeps the contract check, the budget check and the
    per-call ``llm.call`` record but leaves spawn/failure/complete to the caller.
    The verifier needs this: it owns two nested passes (deterministic and model)
    under a single role lifecycle, and letting ``run_agent`` open a second spawn
    for the same role would make the run look like two verifiers, one of which
    never finished.
    """
    store = ctx.store
    contract = sw.check_contract(agent.role, _contract_inputs(ctx))

    spawn = None
    if record_lifecycle:
        spawn = al.record_swarm_event(
            ctx.run_id, role=agent.role, phase="spawn", actor="orchestrator",
            parent_event=ctx.last_event, model_version=ctx.model or "",
            detail={"intent": agent.intent,
                    "requires": contract["required"],
                    "expected_outputs": contract["expected_outputs"]},
            store=store,
        )
    parent = spawn or ctx.last_event

    if not contract["contracted"]:
        if record_lifecycle:
            al.record_swarm_event(
                ctx.run_id, role=agent.role, phase="failure", actor="orchestrator",
                parent_event=parent, error="no role contract",
                detail={"contracted": False}, store=store)
        return AgentResult(role=agent.role, ok=False,
                           error="no role contract", event=spawn)

    missing = contract["missing_inputs"]
    if missing:
        if record_lifecycle:
            al.record_swarm_event(
                ctx.run_id, role=agent.role, phase="failure", actor="orchestrator",
                parent_event=parent, error=f"missing inputs: {', '.join(missing)}",
                detail={"missing_inputs": missing}, store=store)
        return AgentResult(role=agent.role, ok=False,
                           error=f"missing inputs: {', '.join(missing)}",
                           event=spawn)

    budget = sw.budget_allows({**ctx.budget, "llm_calls": ctx.llm_calls},
                              {"llm_calls": ctx.config.swarm_budget_llm_calls,
                               "minutes": ctx.config.swarm_budget_minutes})
    if not budget["allowed"]:
        if record_lifecycle:
            al.record_swarm_event(
                ctx.run_id, role=agent.role, phase="failure", actor="policy",
                parent_event=parent, error="budget exceeded",
                policy=budget, detail={"exceeded": budget["exceeded"]}, store=store)
        return AgentResult(role=agent.role, ok=False, error="budget exceeded",
                           event=spawn)

    # This role's slice of the paper, not the whole thing.
    view = replace(ctx, text=_context_for(agent, ctx.text))
    prompt = agent.build_prompt(view)
    model = ctx.config.ollama_fast_model if agent.fast else (
        ctx.model or ctx.config.ollama_model)
    fingerprint = al.record_prompt_fingerprint(
        ctx.run_id, actor=agent.role, model=model, prompt=prompt,
        context=ctx.text[:4000], detail={"auxiliary": agent.fast}, store=store)

    llm = ctx.llm
    llm.last_served_model = ""
    try:
        data = llm.extract_structured(prompt, model=model, gpu_id=ctx.gpu_id)
    except Exception as e:
        ctx.last_error = str(e)
        al.record_llm_call(ctx.run_id, actor=agent.role, model_requested=model,
                           error=str(e), endpoint="chat",
                           prompt_hash=fingerprint["prompt_hash"], store=store)
        if record_lifecycle:
            al.record_swarm_event(ctx.run_id, role=agent.role, phase="failure",
                                  actor=agent.role, parent_event=parent,
                                  error=str(e), model_version=model, store=store)
        return AgentResult(role=agent.role, ok=False, error=str(e), event=spawn)

    served = getattr(llm, "last_served_model", "") or model
    ctx.llm_calls += 1
    ctx.served_models[agent.role] = served
    ctx.requested_models[agent.role] = model
    al.record_llm_call(ctx.run_id, actor=agent.role, model_requested=model,
                       model_served=served, endpoint="chat",
                       prompt_hash=fingerprint["prompt_hash"],
                       context_hash=fingerprint["context_hash"],
                       detail={"auxiliary": agent.fast}, store=store)

    data = data or {}
    # A role may only contribute the fields its contract declares. Models return
    # extra keys unprompted, and merging them under this role's name would put
    # words in the note that cite the wrong producer -- or silently fill a gap
    # another role left, defeating the explicit NOT_PRODUCED marker.
    data = {k: v for k, v in data.items() if k in agent.fields}
    produced = [f for f in agent.fields if data.get(f) not in (None, "", [], {})]
    empty = [f for f in agent.fields if f not in produced]
    completeness = "complete" if not empty else "partial"

    if record_lifecycle:
        al.record_swarm_event(
            ctx.run_id, role=agent.role,
            phase="complete" if produced else "failure",
            actor=agent.role, parent_event=parent, model_version=served,
            confidence=_confidence_for(agent, data),
            completeness=completeness,
            output_ref=fingerprint["prompt_hash"],
            error=None if produced else "produced no output",
            detail={"produced": {f: data.get(f) for f in produced},
                    "empty_fields": empty, "intent": agent.intent,
                    "auxiliary": agent.fast},
            store=store,
        )

    if empty:
        # Explicit gaps, so the note can show them as gaps rather than as blanks.
        logger.info("%s produced %d/%d fields for %s; missing: %s",
                    agent.role, len(produced), len(agent.fields),
                    ctx.title[:60], ", ".join(empty))

    return AgentResult(role=agent.role, ok=bool(produced), data=data,
                       confidence=_confidence_for(agent, data),
                       produced=produced, empty=empty, event=spawn,
                       served_model=served)


def run_verifier(ctx: AgentContext, analysis: dict[str, Any]) -> dict[str, Any]:
    """Check the merged analysis's numbers against the source text.

    Two independent signals, and both are kept because they fail differently: a
    deterministic substring check that needs no model, and a model verdict that
    can read "roughly 95%" against a table cell reading "95.2". The
    deterministic one is the floor; the model one adds coverage.
    """
    store = ctx.store
    spawn = al.record_swarm_event(
        ctx.run_id, role=VERIFIER_AGENT.role, phase="spawn", actor="orchestrator",
        parent_event=ctx.last_event, intent=VERIFIER_AGENT.intent, store=store)

    deterministic = verify_grounding(ctx.text, analysis)
    claimed = sorted(set(deterministic["supported"]) | set(deterministic["ungrounded"]))
    supported = set(deterministic["supported"])
    claim_hashes: dict[str, str] = {}
    for value in claimed:
        res = lg.emit_claim(ctx.run_id, value, actor=VERIFIER_AGENT.role,
                            seq=None,
                            confidence="high" if value in supported else "low",
                            verdict="supported" if value in supported else "unsupported",
                            verifier="substring", store=store)
        claim_hashes[value] = res["claim_hash"]

    ctx.claims = claimed
    ctx.last_event = spawn or ctx.last_event
    model_verdicts: list[dict[str, Any]] = []
    model_error = ""
    if claimed:
        try:
            # record_lifecycle=False: this run owns the single verifier lifecycle.
            out = run_agent(VERIFIER_AGENT, ctx, record_lifecycle=False)
            if out.ok:
                model_verdicts = (out.data or {}).get("verdicts") or []
            else:
                model_error = out.error or "verifier model pass produced no verdicts"
        except Exception as e:
            model_error = str(e)
        if model_error:
            logger.warning("Verifier model pass failed for %s: %s",
                           ctx.run_id, model_error)

    by_claim = {str(v.get("claim", "")).strip(): v
                for v in model_verdicts if isinstance(v, dict)}
    grounded = [v for v in claimed
                if (v in deterministic["supported"]
                    and by_claim.get(v, {}).get("verdict") in ("supported", None))]
    ungrounded = [v for v in claimed if v not in grounded]
    for value in claimed:
        v = by_claim.get(value, {})
        # The final verdict merges both signals; the event is written once per
        # claim with the evidence behind it, so ``claim.verify`` and the claims
        # table can never disagree about what was checked.
        final = "supported" if value in grounded else (
            "unverified" if v.get("verdict") in ("plausible", None) and
            value in supported else "unsupported")
        lg.verify_claim(ctx.run_id, claim_hashes[value], final,
                        verifier="substring+model",
                        detail={"substring": ("supported" if value in supported
                                              else "unsupported"),
                                "model_verdict": v.get("verdict", "not_assessed"),
                                "note": v.get("note", "")},
                        store=store)
    al.record_swarm_event(
        ctx.run_id, role=VERIFIER_AGENT.role, phase="complete",
        actor=VERIFIER_AGENT.role, parent_event=spawn,
        completeness="complete",
        confidence=(round(len(grounded) / len(claimed), 2) if claimed else None),
        detail={"checked": len(claimed), "grounded": len(grounded),
                "ungrounded": ungrounded,
                "grounded_ratio": deterministic["grounded_ratio"],
                "model_error": model_error or None},
        store=store,
    )

    return {
        "checked": len(claimed),
        "grounded": grounded,
        "ungrounded": ungrounded,
        "grounded_ratio": (round(len(grounded) / len(claimed), 2)
                           if claimed else None),
        "substring_ratio": deterministic["grounded_ratio"],
        "model_verdicts": model_verdicts,
        "model_error": model_error or None,
        "note": deterministic["note"],
    }


def _claim_confidences(grounding: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-claim confidence, for the note's provenance line.

    Three tiers rather than a smooth score, because the evidence is three-tiered:
    a number the model read back and that also appears in the text is solid; one
    the model accepted on paraphrase alone is weaker; one nothing supports is
    worthless. Interpolating between those tiers would invent precision the
    verifier does not have.
    """
    grounded = set(grounding.get("grounded") or [])
    ungrounded = set(grounding.get("ungrounded") or [])
    verdicts = {str(v.get("claim", "")).strip(): v
                for v in (grounding.get("model_verdicts") or [])
                if isinstance(v, dict)}
    out: list[dict[str, Any]] = []
    for value in sorted(grounded | ungrounded):
        v = verdicts.get(value, {})
        if value in grounded:
            confidence = 1.0
        elif str(v.get("verdict")) == "plausible":
            confidence = 0.5
        else:
            confidence = 0.0
        out.append({"claim": value, "grounded": value in grounded,
                    "confidence": confidence,
                    "verdict": v.get("verdict", "not_assessed"),
                    "note": v.get("note", "")})
    return out


# ------------------------------------------------------------ orchestrator --

def build_mandate(paper_id: str, config: Any) -> Mandate:
    """The policy this ingest is bound to, written before the first role runs."""
    return Mandate(
        objective=f"ingest {paper_id} into the research vault",
        planned_intents=[a.intent for a in EXTRACTION_AGENTS] + ["verify_claims"],
        allowed_tools=sw.SHARED_TOOLS,
        allowed_domains=config.swarm_allowed_sources,
        max_llm_calls=config.swarm_budget_llm_calls,
        max_events=config.swarm_budget_llm_calls * 12,
    )


def run_extraction_swarm(*, run_id: str, title: str, text: str, llm: Any,
                         config: Any, figures: Optional[list[dict[str, Any]]] = None,
                         graph_context: str = "", model: Optional[str] = None,
                         gpu_id: Optional[int] = None,
                         hints: Optional[list[str]] = None,
                         store: Optional[LedgerStore] = None) -> dict[str, Any]:
    """Run every extraction role and the verifier, then merge.

    Returns the same shape the old single-prompt path returned, so the rest of
    the pipeline (graph writes, note rendering, RAG chunking) is unchanged — plus
    an ``assurance`` block carrying what the swarm learned about its own run.
    """
    ctx = AgentContext(run_id=run_id, title=title, text=text, llm=llm,
                       config=config, figures=figures or [],
                       graph_context=graph_context, model=model, gpu_id=gpu_id,
                       store=store)

    merged: dict[str, Any] = {}
    results: list[AgentResult] = []
    gaps: dict[str, list[str]] = {}

    for agent in EXTRACTION_AGENTS:
        if hints and agent.role == "contribution-extractor":
            ctx.text = text + (
                "\n\nQuality requirements from the researcher's past feedback "
                "(address all of them):\n- " + "\n- ".join(hints))
        result = run_agent(agent, ctx)
        ctx.text = text  # hints applied to one role only
        results.append(result)
        if result.ok:
            merged.update(result.data)
            ctx.last_event = result.event or ctx.last_event
        if result.empty:
            gaps[agent.role] = result.empty

    # A field a role declared but did not produce becomes an explicit marker
    # rather than a missing key. The note writer branches on the marker, so the
    # section is omitted with a stated reason instead of rendered as a blank
    # that reads as a finding about the paper.
    for agent in EXTRACTION_AGENTS:
        for fieldname in agent.fields:
            if not merged.get(fieldname):
                merged[fieldname] = NOT_PRODUCED

    grounding = run_verifier(ctx, merged)

    required = [a.role for a in EXTRACTION_AGENTS]
    roles_ran = [r.role for r in results if r.ok] + ["verifier"]
    pep = sw.policy_enforcement_point(
        source_kind="full_text" if len(text) > 1500 else "abstract_only_declared",
        min_grounded_ratio=config.swarm_min_grounded_ratio,
        grounded_ratio=grounding["grounded_ratio"],
        required_roles=required, roles_ran=roles_ran,
        figures_found=len(figures or []),
    )

    al.record_tool(run_id, tool="policy.enforcement_point",
                   intent="publish_gate", actor="orchestrator",
                   status="ok" if pep["allowed"] else "deny",
                   detail=pep, store=store)

    critic = sw.critic_review(
        events=_events(run_id, store),
        analysis={k: v for k, v in merged.items()
                  if not isinstance(v, (dict, list))},
        assurance={"grounding": grounding,
                   "provenance": {"analyzed_by": _primary_model(ctx)}},
    )

    failed = [r.role for r in results if not r.ok]
    if failed:
        logger.warning("Extraction roles failed for %s: %s", run_id,
                       ", ".join(failed))

    return {
        **{k: v for k, v in merged.items()},
        "assurance": {
            "roles": [{"role": r.role, "ok": r.ok, "confidence": r.confidence,
                       "produced": r.produced, "empty": r.empty,
                       "error": r.error} for r in results],
            "roles_ran": roles_ran,
            "roles_failed": failed,
            "gaps": gaps,
            "grounding": grounding,
            "claims": _claim_confidences(grounding),
            "policy": pep,
            "critic": critic,
            "served_models": dict(ctx.served_models),
            "requested_models": dict(ctx.requested_models),
            "analyzed_by": _primary_model(ctx),
            "llm_calls": ctx.llm_calls,
        },
    }


def _events(run_id: str, store: Optional[LedgerStore]) -> list[dict[str, Any]]:
    from . import ledger as lg
    try:
        return lg.run_events(run_id, store=store)
    except Exception:
        return []


def _primary_model(ctx: AgentContext) -> str:
    """The model to credit in the note's provenance.

    If the roles were served different models, no single answer is honest. The
    distinct set is then recorded, which is worse for readability and better for
    truth: a reader who sees three names knows the note has no single author,
    where a single name would be a claim nobody checked.

    Auxiliary roles are excluded. The fast tag classifier runs on a different
    model by configuration, and folding it in would put ``configured-model +
    fast-model`` on every note -- which reads as if the prose had two authors
    when only the tags did.
    """
    auxiliary = {a.role for a in EXTRACTION_AGENTS if a.fast}
    served = [v for role, v in ctx.served_models.items()
              if v and role not in auxiliary]
    if not served:
        return ctx.model or ctx.config.ollama_model
    distinct = sorted(set(served))
    return distinct[0] if len(distinct) == 1 else " + ".join(distinct)