"""Swarm events on the ledger, and the integrity monitor that watches them.

:mod:`hive_research.ledger` already gives this system a hash-chained,
append-only event fabric with mandates and export. What it does not give it is
the *assurance* question: not "is the chain intact" but "does the chain show
that the run behaved".

An intact chain proves every event was written once and not edited. It says
nothing about **absence**. A summary written with no verifier event, a note
published with no graph-integrator event, an experiment section that exists but
is empty because the role that fills it failed -- each of those produces a
perfectly valid chain. Those are the failures a research note hides best, and
detecting them is a different job from verifying hashes.

So this module does two things:

1. **Records** the mandatory event classes against the existing ledger, reusing
   its chaining, redaction and export. Prompt content is hashed rather than
   stored by default, which still *proves* what was sent without turning the
   immutable log into a permanent second copy of every paper.
2. **Asserts completeness**: given a run's events, it reports the expected
   events that are missing and raises an integrity alert for each named failure
   mode. Absence becomes a first-class, queryable result.

Ported from the mapper's ``app/assurance_ledger.py``. Every alert there was
written to survive a security assessment; these were re-derived for paper
ingestion, and the reasoning behind each is kept inline because the *reasoning*
is the part worth carrying over, not the threshold.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from . import ledger as lg
from .ledger_models import LedgerStore

#: Swarm event kinds. Recording them is never gated by a mandate -- the audit
#: trail must not be able to refuse to record that it was not asked.
ASSURANCE_KINDS: frozenset[str] = frozenset({
    "swarm.spawn", "swarm.handoff", "swarm.complete", "swarm.failure",
    "run.start", "run.end", "run.degraded", "gate.check",
    "artifact.acquire", "artifact.parse", "artifact.ingest",
    "claim.emit", "claim.verify", "model.prompt", "llm.call",
    "tool.call", "graph.write", "note.publish", "integrity.check",
    "integrity.fail", "human.decision",
})

#: Added to the ledger's never-gated set, so writing the audit trail is never
#: itself an act the mandate can refuse.
#: Kinds that are the audit trail's own machinery, not acts the mandate governs.
#: Only these join the never-gated set. Adding every assurance kind would make
#: ``tool.call`` internal too, which silently disables the mandate's tool and
#: source-domain checks on exactly the events that carry a tool and a source --
#: the checks would exist and never once run.
_INTERNAL_AUDIT_KINDS: frozenset[str] = frozenset({
    "run.start", "run.end", "run.degraded", "gate.check",
    "claim.emit", "claim.verify", "integrity.check", "integrity.fail",
    "audit.dropped", "ledger.fabric",
})
lg.INTERNAL_KINDS = lg.INTERNAL_KINDS | _INTERNAL_AUDIT_KINDS

#: Event classes the monitor expects to find, with the question each answers.
#: Reported as a coverage matrix whether or not it passed, so a reader can see
#: what the run never claimed.
MANDATORY_EVENT_CLASSES: dict[str, str] = {
    "ingest_lifecycle": "Was the paper ingest created, started and completed?",
    "agent_swarm_orchestration": "Did every contracted role run, and who did it?",
    "artifact_acquisition": "Was the source actually fetched, and did it succeed?",
    "extraction_roles": "Did each extraction role produce, or fail explicitly?",
    "claim_grounding": "Was each extracted value checked against the source text?",
    "model_attribution": "Which model produced each result, and what was sent (hashed)?",
    "graph_and_note_publication": "What was written to the graph and the vault?",
    "human_decision": "Who rated, overrode or requested re-analysis, and why?",
    "system_integrity": "Did the fabric itself stay whole?",
}

#: Event kinds that satisfy each mandatory class.
_CLASS_KINDS: dict[str, frozenset[str]] = {
    "ingest_lifecycle": frozenset({"run.start", "run.end", "run.degraded",
                                   "gate.check"}),
    "agent_swarm_orchestration": frozenset({
        "swarm.spawn", "swarm.handoff", "swarm.complete", "swarm.failure"}),
    "artifact_acquisition": frozenset({
        "artifact.acquire", "artifact.parse", "artifact.ingest"}),
    "extraction_roles": frozenset({
        "swarm.complete", "swarm.failure"}),
    "claim_grounding": frozenset({"claim.emit", "claim.verify"}),
    "model_attribution": frozenset({"model.prompt", "llm.call"}),
    "graph_and_note_publication": frozenset({
        "graph.write", "note.publish"}),
    "human_decision": frozenset({"human.decision"}),
    "system_integrity": frozenset({"integrity.check"}),
}

#: Roles that must appear in every complete single-paper ingest.
EXPECTED_SWARM_ROLES = frozenset({
    "source-collector", "document-parser", "tag-classifier",
    "contribution-extractor", "experiment-analyst", "concept-extractor",
    "lineage-tracer", "verifier",
})

#: The fabric's own failure kinds. Deliberately narrow: a blocked policy gate is
#: also severity "block", and folding those in reported every run whose gate was
#: working as "the fabric itself reported a problem" -- an integrity alarm on
#: precisely the run that deserves the most trust.
FABRIC_FAILURE_KINDS = frozenset({"integrity.fail", "audit.dropped", "ledger.fabric"})


# ------------------------------------------------------------- recording ---

def _append(run_id: str, kind: str, actor: str, data: dict[str, Any], *,
            verdict: Optional[str] = None, severity: Optional[str] = None,
            actor_type: str = "system",
            intent: Optional[str] = None,
            store: Optional[LedgerStore] = None) -> Optional[str]:
    """Append one swarm event, tolerating a missing ledger.

    Returns the event hash, or ``None`` when the fabric is unavailable. The
    failure is *recorded* rather than raised: an assurance view that must be
    readable in an environment with no ledger database is still worth
    computing, and the missing events are exactly what :func:`integrity_report`
    looks for.
    """
    try:
        return lg.append(run_id, kind, actor, actor_type=actor_type,
                         intent=intent, data=data, verdict=verdict,
                         severity=severity, checked=False, store=store)
    except Exception:
        return None


def record_run_start(run_id: str, *, actor: str = "orchestrator",
                     paper_id: str = "", mandate: Optional[lg.Mandate] = None,
                     detail: Optional[dict[str, Any]] = None,
                     store: Optional[LedgerStore] = None) -> Optional[str]:
    """Open a run and record the charter it is bound to.

    The mandate is written *before* the first role event, so every later verdict
    is checkable against the policy in force when the run started rather than
    against whatever the policy happens to be at read time.
    """
    try:
        lg.ensure_run(run_id, mandate=mandate, label=paper_id or None, store=store)
    except Exception:
        pass
    lg.set_current_run(run_id, mandate)
    return _append(run_id, "run.start", actor,
                   {"paper_id": paper_id,
                    "mandate_hash": mandate.hash if mandate else None,
                    "mandate": mandate.as_dict() if mandate else {},
                    **(detail or {})},
                   verdict="allow", actor_type="system", intent="start_ingest",
                   store=store)


def record_run_end(run_id: str, *, actor: str = "orchestrator",
                   status: str = "done",
                   detail: Optional[dict[str, Any]] = None,
                   store: Optional[LedgerStore] = None) -> Optional[str]:
    """Close a run, then mark the run row closed so resume knows it settled."""
    h = _append(run_id, "run.end", actor,
                {"status": status, **(detail or {})},
                verdict="allow" if status == "done" else "flag",
                actor_type="system", intent="end_ingest", store=store)
    try:
        lg.close_run(run_id, status="closed" if status == "done" else status,
                     store=store)
    except Exception:
        pass
    lg.set_current_run(None)
    return h


def record_degraded(run_id: str, reason: str, *, actor: str = "orchestrator",
                    fallback: str = "", detail: Optional[dict[str, Any]] = None,
                    store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record that the swarm could not complete and a fallback path ran.

    Degradation is the state that most needs a record. A run that quietly falls
    back to the single-prompt path produces a note indistinguishable from a
    swarm-produced one, which is precisely the ambiguity the swarm was introduced
    to remove.
    """
    return _append(run_id, "run.degraded", actor,
                   {"reason": reason, "fallback": fallback, **(detail or {})},
                   verdict="flag", severity="warn", actor_type="system",
                   intent="degrade", store=store)


def record_swarm_event(run_id: str, *, role: str, phase: str,
                       actor: str = "orchestrator",
                       parent_event: Optional[str] = None,
                       output_ref: Optional[str] = None,
                       intent: Optional[str] = None,
                       confidence: Optional[float] = None,
                       completeness: Optional[str] = None,
                       policy: Optional[dict[str, Any]] = None,
                       error: Optional[str] = None,
                       model_version: Optional[str] = None,
                       detail: Optional[dict[str, Any]] = None,
                       store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record one role acting: spawn, handoff, complete or failure.

    ``phase`` is the lifecycle position; the event kind is derived from it so a
    caller cannot write a "complete" phase under a "failure" kind.
    """
    kinds = {"spawn": "swarm.spawn", "handoff": "swarm.handoff",
             "complete": "swarm.complete", "failure": "swarm.failure"}
    kind = kinds.get(phase, "swarm.spawn")
    data: dict[str, Any] = {"role": role, "phase": phase}
    if parent_event:
        data["parent_event"] = parent_event
    if output_ref:
        data["output_ref"] = output_ref
    if confidence is not None:
        data["confidence"] = confidence
    if completeness:
        data["completeness"] = completeness
    if policy:
        data["policy"] = policy
    if error:
        data["error"] = error
    if model_version:
        data["model_version"] = model_version
    data.update(detail or {})
    return _append(run_id, kind, actor, data,
                   verdict="deny" if phase == "failure" else "allow",
                   severity="warn" if phase == "failure" else "info",
                   actor_type="agent", intent=intent or phase, store=store)


def record_llm_call(run_id: str, *, actor: str, model_requested: str,
                    model_served: str = "", endpoint: str = "chat",
                    prompt_hash: str = "", context_hash: str = "",
                    latency_ms: Optional[int] = None,
                    error: Optional[str] = None,
                    detail: Optional[dict[str, Any]] = None,
                    store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record one inference call, with both the requested and served models.

    This is the single most valuable event in the whole ledger for this app. The
    gateway is allowed to substitute a model, which is right for latency and
    wrong for provenance -- so the two names are recorded separately and
    ``absence_alerts`` raises MODEL-SUBSTITUTION when they diverge.
    """
    data: dict[str, Any] = {
        "model_requested": model_requested, "model_served": model_served,
        "endpoint": endpoint, "prompt_hash": prompt_hash,
        "context_hash": context_hash,
        "model_version": model_served or model_requested,
    }
    if latency_ms is not None:
        data["latency_ms"] = latency_ms
    if error:
        data["error"] = error
    data.update(detail or {})
    return _append(run_id, "llm.call", actor, data,
                   verdict="deny" if error else "allow",
                   severity="warn" if error else "info",
                   actor_type="llm", intent="inference", store=store)


def record_prompt_fingerprint(run_id: str, *, actor: str, model: str,
                              prompt: Optional[str] = None,
                              context: Optional[str] = None,
                              detail: Optional[dict[str, Any]] = None,
                              store: Optional[LedgerStore] = None) -> dict[str, Any]:
    """Hash what was sent rather than storing it.

    The default records a hash, not the text. The ledger is immutable, so a
    stored prompt is a permanent copy of somebody's paper -- and the hash still
    proves *what* was sent, which is the question an audit actually asks.
    """
    ph = lg.text_digest(prompt) if prompt is not None else ""
    ch = lg.text_digest(context) if context is not None else ""
    _append(run_id, "model.prompt", actor,
            {"model": model, "prompt_hash": ph, "context_hash": ch,
             "redaction": "hashed" if not lg.CAPTURE_PAYLOADS else "stored",
             **(detail or {})},
            verdict="allow", actor_type="llm", intent="prompt", store=store)
    return {"prompt_hash": ph, "context_hash": ch}


def record_tool(run_id: str, *, tool: str, intent: str,
                actor: str = "source-collector",
                source: str = "", status: str = "ok",
                latency_ms: Optional[int] = None, error: Optional[str] = None,
                detail: Optional[dict[str, Any]] = None,
                store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record one tool invocation: what was called, from where, with what result."""
    data: dict[str, Any] = {"tool": tool, "source": source, "status": status}
    if latency_ms is not None:
        data["latency_ms"] = latency_ms
    if error:
        data["error"] = error
    data.update(detail or {})
    return _append(run_id, "tool.call", actor, data,
                   verdict="allow" if status == "ok" else "deny",
                   severity="info" if status == "ok" else "warn",
                   actor_type="tool", intent=intent, store=store)


def record_artifact(run_id: str, *, action: str, actor: str = "document-parser",
                    artifact_id: str = "", title: str = "", source: str = "",
                    review: Optional[str] = None,
                    detail: Optional[dict[str, Any]] = None,
                    store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record an artifact lifecycle step (acquire, parse, ingest)."""
    data: dict[str, Any] = {"artifact_id": artifact_id, "action": action,
                            "title": title, "source": source}
    if review:
        data["review"] = review
    data.update(detail or {})
    return _append(run_id, f"artifact.{action}", actor, data,
                   verdict="allow" if review in (None, "accepted") else "flag",
                   severity="info", actor_type="tool", intent=f"artifact_{action}",
                   store=store)


def record_graph_write(run_id: str, *, actor: str = "graph-integrator",
                       node_id: str = "", edges: int = 0,
                       concepts: int = 0, detail: Optional[dict[str, Any]] = None,
                       store: Optional[LedgerStore] = None) -> Optional[str]:
    return _append(run_id, "graph.write", actor,
                   {"node_id": node_id, "edges_written": edges,
                    "concepts_written": concepts, **(detail or {})},
                   verdict="allow", actor_type="tool", intent="write_graph",
                   store=store)


def record_publication(run_id: str, *, note_path: str, actor: str = "note-writer",
                       analyzed_by: str = "", requested_model: str = "",
                       confidence: Optional[float] = None,
                       detail: Optional[dict[str, Any]] = None,
                       store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record that a note reached the vault, with its provenance.

    ``analyzed_by`` and ``requested_model`` are separate on purpose. The gateway
    may have served a different model than was asked for, and a note that claims
    one while the ledger knows the other is a note nobody can trust.
    """
    data: dict[str, Any] = {
        "note_path": note_path, "analyzed_by": analyzed_by,
        "requested_model": requested_model,
        "provenance": {"analyzed_by": analyzed_by,
                       "requested_model": requested_model},
    }
    if confidence is not None:
        data["confidence"] = confidence
    data.update(detail or {})
    return _append(run_id, "note.publish", actor, data,
                   verdict="allow", actor_type="tool", intent="write_note",
                   store=store)


def record_integrity_check(run_id: str, *, check: str, passed: bool,
                           actor: str = "system",
                           detail: Optional[dict[str, Any]] = None,
                           store: Optional[LedgerStore] = None) -> Optional[str]:
    kind = "integrity.check" if passed else "integrity.fail"
    return _append(run_id, kind, actor, {"check": check, "passed": passed,
                                         **(detail or {})},
                   verdict="pass" if passed else "deny",
                   severity="info" if passed else "block",
                   actor_type="system", intent="integrity", store=store)


def record_human_decision(run_id: str, *, actor: str, decision: str,
                          rationale: str = "",
                          paper_id: str = "",
                          confidence_at_decision: Optional[float] = None,
                          detail: Optional[dict[str, Any]] = None,
                          store: Optional[LedgerStore] = None) -> Optional[str]:
    """Record a person's decision. The decision is itself a chained event, so it
    cannot be edited into the record after the fact."""
    data: dict[str, Any] = {"decision": decision, "rationale": rationale,
                            "paper_id": paper_id}
    if confidence_at_decision is not None:
        data["confidence_at_decision"] = confidence_at_decision
    data.update(detail or {})
    return _append(run_id, "human.decision", actor, data,
                   verdict="grant" if decision in ("accept", "accept_with_reserve")
                   else "deny",
                   severity="info", actor_type="human", intent="review",
                   store=store)


# ---------------------------------------------------------------- analysis --

def _load_events(run_id: str, store: Optional[LedgerStore] = None) -> list[dict[str, Any]]:
    try:
        return lg.run_events(run_id, store=store)
    except Exception:
        return []


def class_coverage(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Which mandatory event classes this run recorded.

    Reported whether or not it passed. A coverage matrix that only appears on
    success is a matrix that hides the run which recorded nothing at all.
    """
    evs = list(events)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for e in evs:
        by_kind.setdefault(str(e.get("kind") or ""), []).append(e)

    out: dict[str, dict[str, Any]] = {}
    present = 0
    for cls, question in MANDATORY_EVENT_CLASSES.items():
        kinds = _CLASS_KINDS.get(cls, frozenset())
        hits = [e for k in kinds for e in by_kind.get(k, [])]
        if hits:
            present += 1
        out[cls] = {
            "question": question,
            "recorded": bool(hits),
            "count": len(hits),
            "kinds": sorted(k for k in kinds if by_kind.get(k)),
        }
    return {
        "classes": out,
        "recorded": present,
        "total": len(MANDATORY_EVENT_CLASSES),
        "complete": present == len(MANDATORY_EVENT_CLASSES),
        "completeness_pct": round(present / len(MANDATORY_EVENT_CLASSES) * 100, 0),
        "missing": sorted(c for c, v in out.items() if not v["recorded"]),
    }


def absence_alerts(events: Iterable[dict[str, Any]],
                   expected_roles: Iterable[str] = EXPECTED_SWARM_ROLES,
                   ) -> list[dict[str, Any]]:
    """The failure modes detectable from event absence alone.

    Every alert names the condition, why it matters, and what event would have
    prevented it, so the output is actionable rather than a count.
    """
    evs = list(events)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for e in evs:
        by_kind.setdefault(str(e.get("kind") or ""), []).append(e)
    alerts: list[dict[str, Any]] = []

    def _alert(alert_id: str, severity: str, condition: str, why: str,
               missing: str) -> None:
        alerts.append({
            "id": alert_id, "severity": severity, "condition": condition,
            "why_it_matters": why, "absent_event": missing,
        })

    # --- role coverage ------------------------------------------------------
    # Only raised when the swarm demonstrably started. An ingest that fell back
    # before any role ran has already recorded run.degraded, which is the honest
    # description; reporting every expected role as missing on top of that turns
    # a known fallback into eight invented problems.
    roles_seen: set[str] = set()
    for kind in ("swarm.spawn", "swarm.handoff", "swarm.complete", "swarm.failure"):
        for e in by_kind.get(kind, []):
            r = (e.get("data") or {}).get("role") or e.get("actor") or ""
            if r:
                roles_seen.add(str(r))
    missing_roles = [r for r in expected_roles if r not in roles_seen]
    if missing_roles and (by_kind.get("swarm.spawn") or by_kind.get("swarm.handoff")):
        _alert("ROLE-NEVER-RAN", "block",
               f"Contracted roles with no event: {', '.join(missing_roles)}",
               "A role that never ran leaves its section silently absent, which "
               "reads as a finding about the paper rather than a gap in the "
               "analysis.",
               "swarm.spawn / swarm.complete for the role")

    # --- hand-offs without lineage -----------------------------------------
    unlinked = [e for e in evs
                if str(e.get("kind")) == "swarm.handoff"
                and not (e.get("data") or {}).get("parent_event")]
    if unlinked:
        _alert("HANDOFF-LINEAGE-MISSING", "warn",
               f"{len(unlinked)} hand-off(s) recorded without a parent event",
               "Without a lineage edge the run is a bag of events, not a "
               "sequence, and cannot be replayed.",
               "data.parent_event on every hand-off")

    # --- an empty section where a role should have filled it ----------------
    empty_sections: list[str] = []
    for e in by_kind.get("swarm.complete", []):
        d = e.get("data") or {}
        for key in ("produced", "sections"):
            vals = d.get(key)
            if isinstance(vals, dict):
                empty_sections += [str(k) for k, v in vals.items() if not v]
            elif isinstance(vals, list):
                if not vals:
                    role = str(d.get("role") or "unknown")
                    empty_sections.append(f"{role}:produced")
    if empty_sections:
        _alert("SECTION-EMPTY-NO-GAP", "warn",
               "A role completed with an empty output: " + ", ".join(empty_sections[:6]),
               "An empty section is written into the note as though the paper "
               "said nothing, when in fact the role failed to say anything.",
               "completeness='partial' and an explicit gap list on the event")

    # --- model substitution -------------------------------------------------
    # The gateway substitutes for latency. That is allowed, but a note must not
    # claim one model while a different one wrote it.
    for e in by_kind.get("llm.call", []):
        d = e.get("data") or {}
        req, served = d.get("model_requested"), d.get("model_served")
        if req and served and req != served:
            _alert("MODEL-SUBSTITUTION", "warn",
                   f"Requested {req} but the gateway served {served}",
                   "The note's analyzed_by must name the model that actually "
                   "wrote it, or the provenance is false.",
                   "model_served distinct from model_requested on llm.call")
            break

    # --- a note with no attribution -----------------------------------------
    for e in by_kind.get("note.publish", []):
        d = e.get("data") or {}
        if not (d.get("analyzed_by") or ""):
            _alert("NOTE-WITHOUT-ATTRIBUTION", "block",
                   "A note was published with no analyzed_by recorded",
                   "An unattributed note cannot be told apart from one written "
                   "by a different model than the operator configured.",
                   "analyzed_by on note.publish")
            break

    # --- graph and note out of order ----------------------------------------
    # The note asserts the graph contains what the extraction found. A note
    # published before the graph write means that assertion was never true.
    graph_writes = by_kind.get("graph.write", [])
    publishes = by_kind.get("note.publish", [])
    if graph_writes and publishes:
        if min(p.get("seq", 0) for p in publishes) < min(g.get("seq", 0) for g in graph_writes):
            _alert("NOTE-BEFORE-GRAPH", "warn",
                   "A note was published before the graph was written",
                   "The note's cross-links point at graph state that did not "
                   "exist when it was written.",
                   "graph.write sequenced before note.publish")

    # --- unverified numbers -------------------------------------------------
    emits = by_kind.get("claim.emit", [])
    verifies = by_kind.get("claim.verify", [])
    if emits and not verifies:
        _alert("NUMBERS-NEVER-CHECKED", "block",
               f"{len(emits)} extracted value(s) recorded with no verification event",
               "An extraction nobody checked against the paper is the failure "
               "mode that matters most here: a plausible wrong number in a "
               "summary is worse than an absent one.",
               "claim.verify for each emitted claim")

    ungrounded = [e for e in by_kind.get("claim.verify", [])
                  if (e.get("data") or {}).get("verdict") in ("unsupported", "unverified")]
    if ungrounded:
        _alert("UNGROUNDED-VALUE", "warn",
               f"{len(ungrounded)} extracted value(s) do not appear in the source text",
               "These should be visible in the note as estimates, or removed.",
               "claim.verify verdict='supported'")

    # --- model version drift mid-run ----------------------------------------
    # Auxiliary calls (the fast tag classifier, embeddings) are excluded: the
    # config intends them to use a different model, so counting them would make
    # this alert fire on every single run and teach the reader to ignore it.
    versions: list[tuple[int, str]] = []
    for e in evs:
        data = e.get("data") or {}
        if data.get("auxiliary"):
            continue
        mv = data.get("model_version") or data.get("model")
        if mv:
            versions.append((int(e.get("seq") or 0), str(mv)))
    distinct = sorted({v for _, v in versions})
    if len(distinct) > 1:
        _alert("MODEL-VERSION-CHANGE", "warn",
               "More than one model appears in this run: " + ", ".join(distinct[:4]),
               "A mid-run model change means different sections of one note were "
               "written by different instruments, which should be marked "
               "degraded rather than presented as one voice.",
               "model_version on every hop and llm event")

    # --- fabric's own failures ----------------------------------------------
    fabric_failures = [e for e in evs if str(e.get("kind")) in FABRIC_FAILURE_KINDS]
    if fabric_failures:
        _alert("FABRIC-INTEGRITY-EVENT", "block",
               f"{len(fabric_failures)} integrity-failure event(s) recorded",
               "The fabric itself reported a problem; the run's record cannot "
               "be relied on until it is resolved.",
               "resolution of the recorded anomaly")

    return alerts


def integrity_report(run_id: str, store: Optional[LedgerStore] = None) -> dict[str, Any]:
    """Everything an operator needs to decide whether to trust one ingest."""
    chain = lg.verify_chain(run_id, store=store)
    events = _load_events(run_id, store)
    alerts = absence_alerts(events)
    coverage = class_coverage(events)

    degraded = [e for e in events if str(e.get("kind")) == "run.degraded"]
    blocking = [a for a in alerts if a["severity"] == "block"]
    return {
        "run_id": run_id,
        "ok": chain["ok"] and not blocking,
        "chain_ok": chain["ok"],
        "events": chain["events"],
        "head_hash": chain.get("head_hash"),
        "status": chain.get("status"),
        "class_coverage": coverage,
        "alerts": alerts,
        "blocking_alerts": [a["id"] for a in blocking],
        "degraded": bool(degraded),
        "degradation_reasons": [
            (e.get("data") or {}).get("reason", "") for e in degraded],
        "findings": chain["findings"],
    }


def monitor_integrity(store: Optional[LedgerStore] = None, *,
                      run_ids: Optional[Iterable[str]] = None,
                      limit: int = 40) -> dict[str, Any]:
    """Integrity across recent runs, for the operations view.

    Reports a run as trustworthy only when the chain verifies *and* no blocking
    absence alert fired. Those are different failures and averaging them into one
    number hides the second.
    """
    st = store or lg.get_store()
    if run_ids is None:
        run_ids = [r["id"] for r in lg.list_runs(limit=limit, store=st)]
    runs = []
    blocked = unverified = 0
    for rid in run_ids:
        rep = integrity_report(rid, store=st)
        runs.append({
            "run_id": rid,
            "status": rep.get("status"),
            "events": rep["events"],
            "chain_ok": rep["chain_ok"],
            "degraded": rep["degraded"],
            "blocking_alerts": rep["blocking_alerts"],
            "coverage_pct": rep["class_coverage"]["completeness_pct"],
        })
        if rep["blocking_alerts"]:
            blocked += 1
        if not rep["chain_ok"]:
            unverified += 1
    total = len(runs)
    return {
        "runs": runs,
        "total": total,
        "blocked": blocked,
        "chain_failures": unverified,
        "ok": not blocked and not unverified,
        "trustworthy_rate": (round((total - blocked - unverified) / total, 2)
                             if total else None),
        "note": ("A run is trustworthy only when its chain verifies and no "
                 "blocking absence alert fired. One says the record was not "
                 "edited; the other says it is incomplete."),
    }


def export_siem_events(run_ids: Optional[Iterable[str]] = None, *,
                       store: Optional[LedgerStore] = None,
                       limit: int = 40) -> dict[str, Any]:
    """Export runs in a flat, transport-neutral shape.

    One row per event rather than one object per run: the point of a ledger
    export is to be loadable by something that does not share this schema.
    """
    st = store or lg.get_store()
    if run_ids is None:
        run_ids = [r["id"] for r in lg.list_runs(limit=limit, store=st)]
    rows: list[dict[str, Any]] = []
    for rid in run_ids:
        for e in _load_events(rid, st):
            rows.append({
                "run_id": e["run_id"], "seq": e["seq"], "ts": e["ts"],
                "actor_type": e["actor_type"], "actor": e["actor"],
                "kind": e["kind"], "intent": e.get("intent"),
                "verdict": e.get("verdict"), "severity": e.get("severity"),
                "hash": e["hash"], "prev_hash": e["prev_hash"],
                "summary": _summary_of(e),
            })
    return {"events": rows, "count": len(rows), "runs": list(run_ids)}


_SUMMARY_KEYS = ("role", "phase", "status", "tool", "decision", "reason",
                 "check", "action", "artifact_id", "model_served")


def _summary_of(event: dict[str, Any]) -> str:
    """One-line human summary of an event, built only from known scalar keys.

    Deliberately not a dump of ``data``: this string leaves the system, so it is
    assembled from a fixed key list rather than from whatever a caller happened
    to put in the payload.
    """
    data = event.get("data") or {}
    parts = [f"{data[k]}" for k in _SUMMARY_KEYS if data.get(k) not in (None, "")]
    return " ".join(parts)[:200]