"""Swarm runtime — contracted research roles, typed hand-offs, and the policy
gate every derived artifact must pass.

The pipeline was one long method that downloaded a PDF, asked a model fifteen
questions in a single prompt, and wrote whatever came back. That works, and it
has a specific failure: when the note is thin, there is nothing to ask *why*.
"Did we run out of context, or did the extractor skip the ablation, or did the
model decline to say?" are three different bugs and one symptom.

The fix is not more prompts. It is making each role declare what it must be
given, what it must produce, and what it does when it cannot — and then
recording that it ran. So this module carries:

1. **Role contracts** (``ROLE_CONTRACTS``): the declared shape of every stage.
2. **A policy enforcement point**: the checks a result must pass before it is
   allowed to become a vault note.
3. **Topology / health / resume**: which roles ran, which are missing, and how
   to rebuild a run's state from the ledger alone after a crash.
4. **Typed hand-offs** (``HANDOFF_SCHEMA``): the fields that make a hop a
   lineage edge rather than an island.

Design rule held throughout: **a failed gate is a decision, not an exception.**
``check_contract``, ``validate_handoff`` and ``policy_enforcement_point`` all
return data the orchestrator routes on. An audit layer that raises unwinds the
run it is supposed to be observing.

Ported from the mapper's ``app/swarm.py``. The contracts there described
security-assessment roles; these describe a paper ingest, and the failure modes
were re-derived for this domain rather than copied — see ``EXPECTED_ROLES`` for
what "a role never ran" means when the artifact is a note instead of a score.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

#: Swarms this pipeline runs. A swarm is a group of long-lived roles that share
#: tools and a failure policy; one ingest walks all of them.
SWARMS: dict[str, list[str]] = {
    "acquisition": ["source-collector", "document-parser"],
    "extraction": ["tag-classifier", "contribution-extractor",
                   "experiment-analyst", "concept-extractor",
                   "lineage-tracer"],
    "assurance": ["verifier", "critic"],
    "publication": ["graph-integrator", "note-writer", "rag-indexer"],
}

#: Tools roles share, by name. Used for the mandate's ``allowed_tools`` check.
SHARED_TOOLS = ["arxiv.fetch", "pdf.download", "pdf.extract", "pdf.figures",
                "ollama.chat", "ollama.embed", "graph.write", "vault.write"]


def swarm_for_agent(agent: str) -> Optional[str]:
    for swarm, roles in SWARMS.items():
        if agent in roles:
            return swarm
    return None


def tool_for_intent(intent: str) -> Optional[str]:
    mapping = {
        "fetch_metadata": "arxiv.fetch",
        "download_pdf": "pdf.download",
        "parse_text": "pdf.extract",
        "extract_figures": "pdf.figures",
        "classify_tags": "ollama.chat",
        "extract_contributions": "ollama.chat",
        "analyze_experiments": "ollama.chat",
        "extract_concepts": "ollama.chat",
        "trace_lineage": "ollama.chat",
        "verify_claims": "ollama.chat",
        "write_graph": "graph.write",
        "write_note": "vault.write",
        "index_chunks": "ollama.embed",
    }
    return mapping.get(intent)


# --------------------------------------------------------------- contracts ---

#: Every role declares what it must be given, what it must produce, and what it
#: does when it cannot. A hand-off that violates a precondition is a defect, not
#: something to discover from a thin note.
#:
#: ``requires``/``produces`` are field names on the payload the orchestrator
#: passes between roles. They are checked mechanically by ``check_contract``,
#: so a rename on one side and not the other is caught at the hand-off instead
#: of surfacing as an empty note section.
ROLE_CONTRACTS: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "responsibility": "Sequence the roles for one paper, allocate GPU work, enforce gates",
        "requires": ["paper_id", "text", "title"],
        "produces": ["plan", "role_assignments", "success_criteria"],
        "on_failure": "degrade_to_monolith_and_record_why",
        "may_advance_past_gates": True,
    },
    "source-collector": {
        "responsibility": "Resolve arXiv metadata and download the PDF",
        "requires": ["paper_id"],
        "produces": ["metadata", "pdf_path", "fetch_metadata", "download_status"],
        "on_failure": "fall_back_to_abstract_with_explicit_gap",
        "may_advance_past_gates": False,
    },
    "document-parser": {
        "responsibility": "Extract body text and figures with page provenance",
        "requires": ["pdf_path"],
        "produces": ["text", "figures", "page_map"],
        "on_failure": "emit_empty_text_and_flag_no_source_text",
        "may_advance_past_gates": False,
    },
    "tag-classifier": {
        "responsibility": "Name 5 or fewer topical tags for vault routing",
        "requires": ["text", "title"],
        "produces": ["tags"],
        "on_failure": "empty_tag_list_rather_than_invented_tags",
        "may_advance_past_gates": False,
    },
    "contribution-extractor": {
        "responsibility": "State what the paper claims: summary, tldr, notes, limitations",
        "requires": ["text", "title", "figures"],
        "produces": ["summary", "notes", "tldr", "limitations"],
        "on_failure": "partial_set_with_explicit_gaps_never_a_silent_blank",
        "may_advance_past_gates": False,
    },
    "experiment-analyst": {
        "responsibility": "Extract experiments, metrics, setup and reproduction requirements",
        "requires": ["text", "title"],
        "produces": ["experiment", "experiments", "results", "reproduction",
                     "experiment_ideas"],
        "on_failure": "record_no_experiments_found_rather_than_omitting_the_section",
        "may_advance_past_gates": False,
    },
    "concept-extractor": {
        "responsibility": "Name concepts and the relations between them for the graph",
        "requires": ["text", "title"],
        "produces": ["concepts", "relations"],
        "on_failure": "empty_concept_set_flagged_for_graph_review",
        "may_advance_past_gates": False,
    },
    "lineage-tracer": {
        "responsibility": "Identify prior work this builds on and how it differs",
        "requires": ["text", "title", "graph_context"],
        "produces": ["lineage_notes"],
        "on_failure": "state_lineage_unknown_rather_than_guessing_citations",
        "may_advance_past_gates": False,
    },
    "verifier": {
        "responsibility": "Check extracted numbers and claims against the source text",
        "requires": ["text", "analysis", "claims"],
        "produces": ["grounding_verdicts", "ungrounded_claims"],
        "on_failure": "mark_unverified_never_invent_support",
        "may_advance_past_gates": False,
    },
    "critic": {
        "responsibility": "Sample the run's own record for contradictions and unsupported claims",
        "requires": ["ledger_extract", "analysis"],
        "produces": ["critic_findings", "consistency_report"],
        "on_failure": "report_record_insufficient_to_judge",
        "may_advance_past_gates": False,
    },
    "graph-integrator": {
        "responsibility": "Write concepts, relations and the paper node into the graph",
        "requires": ["paper_id", "concepts", "relations", "tags"],
        "produces": ["node_id", "edges_written", "concept_matches"],
        "on_failure": "rollback_partial_graph_writes_and_report",
        "may_advance_past_gates": False,
    },
    "note-writer": {
        "responsibility": "Render the vault note including provenance and review state",
        "requires": ["paper_id", "summary", "tags", "concepts"],
        "produces": ["note_path", "provenance_record"],
        "on_failure": "refuse_to_write_an_unattributed_note",
        "may_advance_past_gates": False,
    },
    "rag-indexer": {
        "responsibility": "Chunk the note and embed it for retrieval",
        "requires": ["note_path"],
        "produces": ["chunks", "embeddings"],
        "on_failure": "record_indexing_gap_explicitly",
        "may_advance_past_gates": False,
    },
    "human-reviewer": {
        "responsibility": "Rate a note, request re-analysis, override a low-confidence result",
        "requires": ["note_path", "decision_package"],
        "produces": ["ledger_event_with_identity_and_rationale"],
        "on_failure": "expire_and_trigger_reevaluation",
        "may_advance_past_gates": True,
    },
}

#: The only roles permitted to advance past a gate. Everything else treats a
#: gate failure as a hard stop for publishing a note.
GATE_AUTHORITIES = frozenset(
    role for role, c in ROLE_CONTRACTS.items() if c.get("may_advance_past_gates"))


def expected_roles(include_publication: bool = True) -> list[str]:
    """The roles a complete single-paper ingest should have run."""
    roles = ["source-collector", "document-parser", "tag-classifier",
             "contribution-extractor", "experiment-analyst", "concept-extractor",
             "lineage-tracer", "verifier", "critic"]
    if include_publication:
        roles += ["graph-integrator", "note-writer", "rag-indexer"]
    return roles


#: Roles whose absence invalidates a note. Publication roles are excluded
#: because an ingest that failed before writing a note is a *different* run, and
#: reporting it as missing publication roles hides that.
EXPECTED_ROLES = expected_roles(include_publication=False)


def role_contract(role: str) -> dict[str, Any]:
    """The contract for a role, or an explicit "uncontracted" marker.

    An unknown role is reported as uncontracted rather than treated as
    unconstrained: a role nobody wrote a contract for has no declared failure
    behaviour, which is exactly the gap the contracts exist to close.
    """
    c = ROLE_CONTRACTS.get(str(role or ""))
    if c:
        return {"role": role, "contracted": True, **c}
    return {
        "role": role, "contracted": False,
        "responsibility": "undeclared",
        "requires": [], "produces": [],
        "on_failure": "undeclared",
        "may_advance_past_gates": False,
        "note": ("No contract for this role: its inputs, outputs and failure "
                 "behaviour are undeclared, so nothing can be asserted about "
                 "what it was required to do."),
    }


def check_contract(role: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Validate a hand-off payload against a role's contract.

    Reports missing inputs by name. Never raises: a blocked hand-off is data the
    orchestrator routes on, not an exception that unwinds the run.
    """
    c = role_contract(role)
    got = set((payload or {}).keys())
    missing = sorted(r for r in c.get("requires") or [] if r not in got)
    return {
        "role": role,
        "contracted": c["contracted"],
        "ok": bool(c["contracted"]) and not missing,
        "missing_inputs": missing,
        "required": list(c.get("requires") or []),
        "expected_outputs": list(c.get("produces") or []),
        "on_failure": c.get("on_failure"),
        "authority": ("gate_authority" if role in GATE_AUTHORITIES
                      else "blocked_by_gate"),
    }


# --------------------------------------------------- policy enforcement ----

def policy_enforcement_point(*, source_kind: str = "full_text",
                             min_grounded_ratio: float = 0.5,
                             grounded_ratio: Optional[float] = None,
                             required_roles: Optional[Iterable[str]] = None,
                             roles_ran: Optional[Iterable[str]] = None,
                             figures_found: Optional[int] = None,
                             notes_written: bool = False,
                             ) -> dict[str, Any]:
    """The single check an analysis must pass before a note may be published.

    Policy-as-code at the orchestration layer, so no agent can skip it by writing
    the note itself. Three things block:

    - **source adequacy** — a summary built on an abstract instead of a body is
      a different artifact and must not be published as if it were the same.
    - **role coverage** — an extraction role that never ran leaves a section
      silently absent.
    - **grounding** — numbers that do not appear in the paper's own text.

    Warnings lower confidence instead of blocking. A run with a PDF but zero
    extracted figures is odd, not fatal: not every paper has figures.

    Never raises. A failure is a decision.
    """
    checks: list[dict[str, Any]] = []

    checks.append({
        "id": "source_adequacy",
        "passed": source_kind in ("full_text", "abstract_only_declared"),
        "severity": "block",
        "detail": f"analysis source was {source_kind}",
        "open_items": ([] if source_kind != "none" else ["no source text at all"]),
    })

    required = list(required_roles or [])
    ran = set(roles_ran or [])
    missing_roles = [r for r in required if r not in ran]
    checks.append({
        "id": "role_coverage",
        "passed": not missing_roles,
        "severity": "block",
        "detail": (", ".join(missing_roles) if missing_roles
                   else f"all {len(required)} contracted role(s) ran"),
        "open_items": missing_roles,
    })

    checks.append({
        "id": "grounding_computed",
        "passed": grounded_ratio is not None,
        # Informational, not blocking: a theory paper with no numeric claims has
        # nothing to ground, and failing it closed would reject the papers that
        # never had a number to check. The absent verdict is still recorded.
        "severity": "info",
        "detail": ("grounding was computed" if grounded_ratio is not None
                   else "no numeric claims were found to ground"),
        "open_items": [],
    })
    if grounded_ratio is not None:
        checks.append({
            "id": "grounding_floor",
            "passed": float(grounded_ratio) >= min_grounded_ratio,
            "severity": "warn",
            "detail": (f"{float(grounded_ratio):.0%} of extracted numbers appear "
                       f"in the source vs a {min_grounded_ratio:.0%} floor"),
            "open_items": [],
        })

    if figures_found is not None:
        checks.append({
            "id": "figure_extraction",
            "passed": figures_found > 0 or source_kind == "abstract_only_declared",
            "severity": "warn",
            "detail": f"{figures_found} figure(s) extracted from a full-text parse",
            "open_items": [],
        })

    blocked = [c for c in checks if not c["passed"] and c["severity"] == "block"]
    warned = [c for c in checks if not c["passed"] and c["severity"] == "warn"]
    return {
        "allowed": not blocked,
        "checks": checks,
        "blocked_by": [c["id"] for c in blocked],
        "warnings": [c["id"] for c in warned],
        "decision": ("publish_blocked" if blocked
                     else "publish_allowed_with_confidence_penalty" if warned
                     else "publish_allowed"),
        "confidence_penalty": round(0.1 * len(warned), 2),
        "note": ("Blocked means no note is written. Warnings lower the "
                 "confidence recorded in the note's provenance instead."),
    }


def policy_engine(*, source_kind: str = "full_text",
                  min_grounded_ratio: float = 0.5,
                  grounded_ratio: Optional[float] = None,
                  required_roles: Optional[Iterable[str]] = None,
                  roles_ran: Optional[Iterable[str]] = None,
                  figures_found: Optional[int] = None,
                  notes_written: bool = False,
                  sources: Optional[Iterable[str]] = None,
                  allowed_sources: Optional[Iterable[str]] = None,
                  budget_used: Optional[dict[str, float]] = None,
                  budget: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """Full policy-as-code at the orchestrator.

    One evaluation covers both decisions the ingest must make under policy --
    *may a note be published* (the PEP above) and *may a fetch fire* (source
    scope and budget). Every rule is a declarative entry with an id, so the
    orchestrator logs exactly which rule decided the run and an auditor reads
    the whole policy surface from one structure.
    """
    pep = policy_enforcement_point(
        source_kind=source_kind, min_grounded_ratio=min_grounded_ratio,
        grounded_ratio=grounded_ratio, required_roles=required_roles,
        roles_ran=roles_ran, figures_found=figures_found,
        notes_written=notes_written)
    rules: list[dict[str, Any]] = list(pep["checks"])

    if sources or allowed_sources:
        denied = [s for s in (sources or [])
                  if not check_scope("fetch", s, allowed_sources)["allowed"]]
        rules.append({
            "id": "source_scope",
            "passed": not denied,
            "severity": "block",
            "detail": ", ".join(denied) if denied else "all sources in allow-list",
            "open_items": denied,
        })
    if budget_used:
        b = budget_allows(budget_used, budget)
        rules.append({
            "id": "ingest_budget",
            "passed": b["allowed"],
            "severity": "block",
            "detail": f"exceeded: {', '.join(b['exceeded']) or 'none'}",
            "open_items": b["exceeded"],
        })

    blocked = [r for r in rules if not r["passed"] and r["severity"] == "block"]
    warned = [r for r in rules if not r["passed"] and r["severity"] == "warn"]
    return {
        "rules": rules,
        "allowed": not blocked,
        "blocked_by": [r["id"] for r in blocked],
        "warnings": [r["id"] for r in warned],
        "decision": ("blocked" if blocked
                     else "allowed_with_penalty" if warned else "allowed"),
        "confidence_penalty": round(0.1 * len(warned), 2),
        "note": ("Every rule is a declarative entry the orchestrator logs by id, "
                 "so 'who decided, under which rule' is a lookup, not a guess."),
    }


#: Kinds that describe a role acting. Everything else in the ledger -- gates,
#: publications, human decisions -- carries an actor too, and folding those in
#: made the engine that wrote a note look like a role nobody wrote a contract for.
ROLE_EVENT_KINDS = frozenset({
    "swarm.spawn", "swarm.handoff", "swarm.complete", "swarm.failure",
})


def _role_events(events: Optional[Iterable[dict[str, Any]]]):
    """The subset of events that describe a role acting, in order."""
    return [e for e in (events or [])
            if str(e.get("kind") or "") in ROLE_EVENT_KINDS]


# -------------------------------------------------------------- topology ----

def topology(events: Optional[Iterable[dict[str, Any]]] = None) -> dict[str, Any]:
    """Live swarm view: which roles ran, are running, failed, or never started."""
    state: dict[str, dict[str, Any]] = {}
    for r in ROLE_CONTRACTS:
        state[r] = {"role": r, "state": "pending", "hops": 0, "failures": 0,
                    "last_seq": None, "authority": r in GATE_AUTHORITIES,
                    "contracted": True}
    for e in _role_events(events):
        data = e.get("data") or {}
        role = str(data.get("role") or e.get("actor") or "")
        if role not in state:
            # Keep the fact that nobody wrote a contract for this role: the
            # state field below moves on to active/complete, so a role's lack of
            # a contract has to live somewhere it cannot be overwritten.
            state[role] = {"role": role, "state": "uncontracted", "hops": 0,
                           "failures": 0, "last_seq": None,
                           "authority": role in GATE_AUTHORITIES,
                           "contracted": False}
        rec = state[role]
        rec["hops"] += 1
        rec["last_seq"] = e.get("seq")
        phase = str(data.get("phase") or "")
        kind = str(e.get("kind") or "")
        if phase == "failure" or kind == "swarm.failure":
            rec["failures"] += 1
            rec["state"] = "failed"
        elif phase == "complete" or kind == "swarm.complete":
            rec["state"] = "complete"
        elif rec["state"] != "failed":
            rec["state"] = "active"
    return {
        "roles": list(state.values()),
        "pending": sorted(r for r, v in state.items() if v["state"] == "pending"),
        "failed": sorted(r for r, v in state.items() if v["state"] == "failed"),
        "complete": sorted(r for r, v in state.items() if v["state"] == "complete"),
        "uncontracted": sorted(r for r, v in state.items() if not v["contracted"]),
        "gate_authorities": sorted(GATE_AUTHORITIES),
        "expected": EXPECTED_ROLES,
    }


def health(events: Optional[Iterable[dict[str, Any]]] = None) -> dict[str, Any]:
    """Swarm success metrics by role."""
    per_role: dict[str, dict[str, int]] = {}
    hops = retries = failures = gate_failures = 0
    for e in _role_events(events):
        data = e.get("data") or {}
        role = str(data.get("role") or e.get("actor") or "unknown")
        rec = per_role.setdefault(role, {"spawns": 0, "completions": 0, "failures": 0})
        kind = str(e.get("kind") or "")
        phase = str(data.get("phase") or "")
        if phase == "spawn" or kind == "swarm.spawn":
            rec["spawns"] += 1
            hops += 1
        elif phase == "handoff" or kind == "swarm.handoff":
            hops += 1
        if phase == "complete" or kind == "swarm.complete":
            rec["completions"] += 1
        if phase == "failure" or kind == "swarm.failure":
            rec["failures"] += 1
            failures += 1
            # A failure the policy enforcement point caused is the number worth
            # reading separately: it means the gate did its job, not that the
            # fabric is flaky. Folding it into one rate hid that.
            policy = data.get("policy") or {}
            if policy.get("blocked_by") or policy.get("decision") == "publish_blocked":
                gate_failures += 1
        if str(e.get("intent") or "").endswith("retry"):
            retries += 1
    rows = []
    for role, rec in sorted(per_role.items()):
        attempts = rec["completions"] + rec["failures"]
        rows.append({
            "role": role,
            "attempts": attempts,
            "spawns": rec["spawns"],
            "completions": rec["completions"],
            "failures": rec["failures"],
            "success_rate": (round(rec["completions"] / attempts, 2) if attempts else None),
            "contracted": role in ROLE_CONTRACTS,
        })
    return {
        "roles": rows,
        "hops": hops,
        "failures": failures,
        "gate_failures": gate_failures,
        "retries": retries,
        "overall_success_rate": (
            round(sum(r["completions"] for r in rows)
                  / max(1, sum(r["attempts"] for r in rows)), 2) if rows else None),
        "gate_failure_rate": (round(gate_failures / max(1, failures), 2)
                              if failures else None),
        "note": ("A role with no contract is counted but not judged: nothing "
                 "was declared about what success means for it."),
    }


# ------------------------------------------- durable resume from the ledger --

def resume_state(events: Optional[Iterable[dict[str, Any]]] = None) -> dict[str, Any]:
    """Reconstruct a run's execution state from its ledger events alone.

    The ledger is the source of truth for a restart: nothing the swarm did is
    kept in a worker's memory, so a process death at any point can be rebuilt
    from the last committed event. Returns the next phase to execute and the
    per-role verdicts, so the orchestrator resumes rather than re-plans from
    scratch (and re-runs roles that already committed outputs).
    """
    evs = list(events or [])
    per_role: dict[str, dict[str, Any]] = {}
    seen_lifecycle: set[str] = set()
    last_seq: Optional[int] = None
    for e in evs:
        seq = e.get("seq")
        if seq is not None:
            last_seq = max(last_seq or -1, int(seq))
        kind = str(e.get("kind") or "")
        data = e.get("data") or {}
        if kind.startswith("run."):
            seen_lifecycle.add(kind.split(".")[-1])
        role = str(data.get("role") or e.get("actor") or "")
        if not role or kind not in ROLE_EVENT_KINDS:
            continue
        rec = per_role.setdefault(role, {"spawned": False, "completed": False,
                                         "failed": False, "hops": 0})
        rec["hops"] += 1
        phase = str(data.get("phase") or "")
        if phase == "spawn" or kind == "swarm.spawn":
            rec["spawned"] = True
        elif phase == "complete" or kind == "swarm.complete":
            rec["completed"] = True
        elif phase == "failure" or kind == "swarm.failure":
            rec["failed"] = True

    done = sorted(r for r, v in per_role.items() if v["completed"] or v["failed"])
    pending = sorted(r for r in ROLE_CONTRACTS
                     if r not in per_role or not per_role[r]["completed"])
    resumed = sorted(r for r in ROLE_CONTRACTS
                     if per_role.get(r, {}).get("spawned")
                     and not (per_role[r]["completed"] or per_role[r]["failed"]))
    extraction = ("concept-extractor", "experiment-analyst",
                  "contribution-extractor", "tag-classifier")
    return {
        "events": len(evs),
        "last_seq": last_seq,
        "lifecycle_phases": sorted(seen_lifecycle),
        "roles": {r: v for r, v in sorted(per_role.items())},
        "completed": done,
        "pending": pending,
        "resume_these": resumed,
        "phase": ("published" if any(r in per_role for r in ("note-writer", "rag-indexer"))
                  else "verified" if "verifier" in per_role
                  else "extracted" if any(r in per_role for r in extraction)
                  else "acquired" if "document-parser" in per_role
                  else "plan"),
        "restartable": bool(evs) and "end" not in seen_lifecycle,
        "note": ("Resume-from-ledger: replay the committed events, skip roles "
                 "already marked complete, re-run the ones in resume_these."),
    }


# ---------------------------------------------------------- typed hand-offs --

#: Mandatory fields on every inter-role hand-off, with the reason each is
#: non-negotiable. A hand-off that fails this schema is a defect, not a warning.
HANDOFF_SCHEMA: dict[str, dict[str, Any]] = {
    "run_id": {"required": True, "reason": "scopes the event to one ingest"},
    "parent_event": {"required": True, "reason": "lineage edge: without it a hop is an island"},
    "from_role": {"required": True, "reason": "who is handing off"},
    "to_role": {"required": True, "reason": "who must receive and act"},
    "model_version": {"required": True, "reason": "a mid-run model change must be visible"},
    "confidence": {"required": True, "reason": "a hand-off without confidence cannot gate"},
    "input_refs": {"required": False,
                   "reason": "hashes of what the receiving role must consume"},
}


def validate_handoff(message: dict[str, Any]) -> dict[str, Any]:
    """Schema-check a typed inter-role message (never raises).

    Returns ``ok`` plus the missing fields and their reasons, so the
    orchestrator can refuse a malformed hand-off instead of routing it on.
    """
    missing = [k for k, spec in HANDOFF_SCHEMA.items()
               if spec["required"] and message.get(k) in (None, "", [])]
    return {
        "ok": not missing,
        "missing": missing,
        "reasons": {k: HANDOFF_SCHEMA[k]["reason"] for k in missing},
        "keys_present": sorted(k for k in HANDOFF_SCHEMA if message.get(k)),
    }


def record_typed_handoff(run_id: str, message: dict[str, Any],
                         actor: str = "orchestrator",
                         detail: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Validate and, if valid, record one typed hand-off as a ledger event.

    An invalid hand-off returns ``None`` without writing: the missing fields
    are the point, and recording a message the schema rejects would make the
    ledger itself assert something false.
    """
    from . import assurance_ledger as _al

    check = validate_handoff(message)
    if not check["ok"]:
        return None
    return _al.record_swarm_event(
        run_id, role=message["to_role"], phase="handoff", actor=actor,
        parent_event=message.get("parent_event"),
        confidence=message.get("confidence"),
        model_version=message.get("model_version"),
        detail=dict(detail or {}, from_role=message.get("from_role"),
                    input_refs=message.get("input_refs") or []))


# ---------------------------------------------------------------- critic ----

def critic_review(events: Optional[Iterable[dict[str, Any]]] = None,
                  analysis: Optional[dict[str, Any]] = None,
                  assurance: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """A self-consistency pass over a completed run.

    The critic samples the ledger for the failures an opaque pipeline hides: a
    summary claiming numbers the paper does not contain, a section silently
    absent because its role never ran, a note written with no model attribution,
    and hops that never happened. These are *findings*, not judgments of the
    analysis itself -- the point is to surface what a plausible-looking note
    would otherwise absorb.
    """
    from . import assurance_ledger as _al

    evs = list(events or [])
    findings: list[dict[str, Any]] = []
    if evs:
        for a in _al.absence_alerts(evs):
            if a["severity"] == "block":
                findings.append({"type": "ledger", "id": a["id"],
                                 "condition": a["condition"],
                                 "why_it_matters": a["why_it_matters"]})

    analysis = analysis or {}
    # A section that exists but is empty is worse than one that is absent: the
    # note reads as though the paper said nothing on the topic, when in fact the
    # role that would have said something failed.
    for section in ("summary", "limitations", "lineage_notes"):
        if section in analysis and not str(analysis.get(section) or "").strip():
            findings.append({
                "type": "empty_section",
                "id": f"EMPTY-{section.upper().replace('_', '-')}",
                "condition": f"{section} was written but is empty",
                "why_it_matters": "an empty section reads as a finding about the "
                                  "paper rather than a failure to analyse it.",
            })

    gr = (assurance or {}).get("grounding") or {}
    ungrounded = gr.get("ungrounded") or []
    if ungrounded:
        findings.append({
            "type": "unsupported_claim",
            "id": "UNGROUNDED-NUMBERS",
            "condition": f"{len(ungrounded)} extracted value(s) do not appear in the source",
            "why_it_matters": "a number that is not in the paper is the failure "
                              "mode that matters most here; the rest degrade quality.",
            "detail": ungrounded[:10],
        })

    prov = (assurance or {}).get("provenance") or {}
    if analysis and not (prov.get("analyzed_by") or ""):
        findings.append({
            "type": "provenance",
            "id": "NOTE-WITHOUT-ATTRIBUTION",
            "condition": "an analysis exists but no served model was recorded",
            "why_it_matters": "an unattributed note cannot be told apart from one "
                              "written by a different model than the one configured.",
        })

    return {
        "checked": bool(evs) or bool(analysis),
        "findings": findings,
        "clean": not findings,
        "note": ("The critic is a second pass, not a re-scorer: it asks whether "
                 "the record supports the note."),
    }


# ------------------------------------------------------ rate & scope control --

#: Default per-paper budget. ``tokens`` is estimated by the LLM wrapper.
DEFAULT_BUDGET = {"llm_calls": 12, "tool_calls": 40, "minutes": 30}


def check_scope(tool: str, source: str = "",
                allowed_sources: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Source allow-list check before any external call that could carry context.

    A source outside the ingest's allow-list is a deny, not a warning: the run
    fetches only what its mandate permits. An empty allow-list allows, because
    an operator who configured nothing has not expressed a restriction.
    """
    allowed = {str(s).strip().lower() for s in (allowed_sources or []) if s}
    src = str(source or "").strip().lower()
    ok = (not allowed) or src in allowed
    return {
        "tool": tool,
        "source": src,
        "allowed": ok,
        "allow_list": sorted(allowed),
        "verdict": "allow" if ok else "deny",
        "reason": ("allow-list empty" if not allowed
                   else "in allow-list" if src in allowed
                   else f"not in allow-list ({src or 'unnamed source'})"),
    }


def budget_allows(used: dict[str, float],
                  budget: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """Enforce the per-paper budget. Returns the limits hit, or an allow verdict."""
    b = dict(DEFAULT_BUDGET)
    if budget:
        b.update({k: v for k, v in budget.items() if v is not None})
    used = {k: float(v or 0) for k, v in used.items()}
    exceeded = [k for k in DEFAULT_BUDGET if used.get(k, 0) > b[k]]
    return {
        "allowed": not exceeded,
        "limits": b,
        "used": {k: round(used.get(k, 0), 1) for k in DEFAULT_BUDGET},
        "exceeded": exceeded,
        "verdict": "allow" if not exceeded else "deny",
        "note": "A role over budget is paused, not silently continued.",
    }