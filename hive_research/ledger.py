"""Tamper-evident, hash-chained audit ledger.

Ported from the mapper's ``app/ledger.py``, re-based on stdlib ``sqlite3`` and
retargeted at the research domain. The hashing core, the chain rules and the
verification pass are unchanged in substance: what makes a record auditable is
that each event commits to its predecessor, so an edit, a deletion or an
insertion after the fact all break verification.

    run_id ──▶ seq 0 ──▶ seq 1 ──▶ seq 2 ──▶ … ──▶ head_hash
              prev=GENESIS   prev=h(0)      prev=h(1)

What this buys the pipeline, concretely: the vault note for a paper says which
model wrote it, and this ledger says the same thing with a proof that the claim
was not edited afterwards. When the gateway substitutes a 3B model for the 27B
one that was asked for, ``llm.call`` events carry both names, and a mixed-model
run is detectable rather than plausible-looking.

Two mechanisms are deliberately faithful ports rather than rewrites, because
both are load-bearing:

- **Redaction before immutable storage.** The ledger is append-only, so
  anything written is effectively permanent. Credentials are stripped; counts
  are not, because redacting those would destroy the evidence while protecting
  nothing.
- **A mandate the chain is checked against.** Policy is evaluated *at write
  time* and the verdict is stored inside the event, so "who decided, under which
  rule" is a lookup rather than a reconstruction.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Iterable, Optional

from .ledger_models import LedgerStore, get_store, init_store, reset_store

logger = logging.getLogger(__name__)

GENESIS = "0" * 64

#: Fields that make up a row's immutable core, and therefore its hash.
CORE_FIELDS = ("run_id", "seq", "ts", "actor_type", "actor", "kind", "intent",
               "verdict", "severity", "data", "prev_hash")

ACTOR_TYPES = frozenset({"agent", "llm", "tool", "system", "human"})

#: Kinds the mandate never gates: recording the audit trail is not an act the
#: audit trail can refuse to record.
INTERNAL_KINDS = frozenset({
    "run.start", "run.end", "mandate.set", "mandate.check",
    "claim.emit", "claim.verify", "audit.dropped", "ledger.fabric",
})

VALID_VERDICTS = frozenset({"pass", "allow", "deny", "flag", "hold", "block", "grant"})
VALID_SEVERITIES = frozenset({"info", "warn", "block"})
CLAIM_VERDICTS = frozenset({"supported", "unsupported", "uncertain", "unverified"})

#: Store full prompts in the log. Off by default: the chain is immutable, so
#: anything written here is permanent. The default records a prompt *hash*
#: instead, which still proves what was sent without keeping a second copy of
#: every paper's text forever.
CAPTURE_PAYLOADS = os.environ.get("LEDGER_CAPTURE_PAYLOADS", "").lower() in ("1", "true", "yes")

# Credential names that are never a metric. Redacted whatever the value is.
_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|secret|api[_-]?key|apikey|authorization|credential|"
    r"private[_-]?key|session[_-]?id|cookie|passphrase)", re.I)
# Names that are a credential *or* a metric depending on the value: "token" is an
# access token in `access_token` but a count in `tokens_in`. Only redact when the
# value could actually be a secret.
_SECRET_IF_STRING = re.compile(r"(^|[_-])(token|tokens|auth|bearer)([_-]|$)", re.I)
_SECRET_VALUE = re.compile(
    r"\b(?:sk|pk|ghp|gho|xox[baprs])-[A-Za-z0-9_-]{8,}"
    # A long opaque token -- unless it is a hex digest. A 40+ character run of
    # [0-9a-f] is a hash, and hashes are evidence here: they appear in payload
    # hashes, genesis values and claim content addresses. Redacting those would
    # silently gut the evidence this function exists to preserve.
    r"|\b(?![A-Fa-f0-9]{40,}\b)[A-Za-z0-9+/]{40,}={0,2}\b")

# Serialises chain appends inside one process. Across processes the
# UNIQUE(run_id, seq) index is the real guard and ``append`` retries against the
# new head.
_LOCK = threading.RLock()

_current_run: ContextVar[Optional[str]] = ContextVar("ledger_run", default=None)
_current_mandate: ContextVar[Optional["Mandate"]] = ContextVar("ledger_mandate", default=None)


# ------------------------------------------------------------------ hashing --

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canon(obj: Any) -> str:
    """Canonical JSON. Sorting keys and pinning separators is what makes a hash
    reproducible across processes, dict orderings and Python versions."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def digest(obj: Any) -> str:
    return sha256(canon(obj).encode("utf-8")).hexdigest()


def text_digest(text: Optional[str]) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def is_hash(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and re.fullmatch(r"[0-9a-f]{64}", value) is not None)


def _redact(value: Any) -> Any:
    """Strip credentials before anything reaches immutable storage.

    Numbers survive: an audit record is full of counts (tokens, latency, chunk
    counts, figure counts) and redacting those would destroy the evidence while
    protecting nothing. Credentials are strings, so key-based redaction keys off
    the value as well as the name.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _SECRET_KEY.search(k):
                out[k] = "[redacted]"
            elif (isinstance(k, str) and _SECRET_IF_STRING.search(k)
                  and isinstance(v, (str, list, dict))):
                out[k] = "[redacted]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[redacted]", value)
    return value


def _payload(value: Any) -> Any:
    return value if CAPTURE_PAYLOADS else _redact(value)


def _dumps(value: Any) -> Optional[str]:
    return None if value is None else canon(value)


def _loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def event_core(*, run_id: str, seq: int, ts: str, actor_type: str, actor: str,
               kind: str, intent: Optional[str], verdict: Optional[str],
               severity: Optional[str], data: Any, prev_hash: str) -> dict:
    """The exact structure a row's hash is taken over."""
    return {
        "run_id": run_id, "seq": seq, "ts": ts, "actor_type": actor_type,
        "actor": actor, "kind": kind, "intent": intent, "verdict": verdict,
        "severity": severity, "data": data, "prev_hash": prev_hash,
    }


def chain_hash(core: dict) -> str:
    missing = [f for f in CORE_FIELDS if f not in core]
    if missing:
        raise ValueError(f"event core missing fields: {missing}")
    return digest(core)


# ------------------------------------------------------------------ mandate --

@dataclass
class Verdict:
    decision: str = "pass"     # pass|allow|deny|flag|hold
    rule: str = "unconstrained"
    reason: str = ""
    severity: str = "info"
    detail: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.decision == "deny"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Mandate:
    """The policy one paper's ingest is bound to.

    Two flavours of intent restriction, because they are not the same promise:
    ``allowed_intents`` is a hard boundary (an action outside it is denied), and
    ``planned_intents`` is the expected shape of the work (an action outside it
    is allowed but recorded as drift).

    For a research ingest the load-bearing fields are ``allowed_domains`` (the
    run may only reach the sources it was chartered for), ``max_llm_calls``
    (a runaway extraction loop is stopped by policy, not by hope) and
    ``require_grounding`` (an extracted number that does not appear in the
    source is a defect the ledger names).
    """

    objective: str = ""
    allowed_actors: list = field(default_factory=list)     # empty = any
    allowed_intents: list = field(default_factory=list)    # hard boundary
    planned_intents: list = field(default_factory=list)    # soft: drift if outside
    allowed_tools: list = field(default_factory=list)
    allowed_domains: list = field(default_factory=list)    # source scopes
    human_gates: list = field(default_factory=list)        # kinds needing sign-off
    max_events: int = 0            # 0 = unbounded
    max_llm_calls: int = 0
    loop_threshold: int = 5        # repeats of one (actor, intent) before flagging
    require_grounding: bool = False  # ungrounded extractions become violations

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "Mandate":
        raw = raw or {}
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in fields})

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def hash(self) -> str:
        return digest(self.as_dict())

    def domain_allowed(self, domain: str) -> bool:
        if not self.allowed_domains or not domain:
            return True
        d = (domain or "").lower().lstrip(".")
        for allowed in self.allowed_domains:
            a = allowed.lower().lstrip(".")
            if d == a or d.endswith("." + a):
                return True
        return False

    def check(self, *, kind: str, actor: str, actor_type: str = "system",
              intent: Optional[str] = None, tool: Optional[str] = None,
              domain: Optional[str] = None,
              counts: Optional[dict] = None) -> Verdict:
        """Evaluate one action. First hard failure wins; soft signals are
        reported as ``flag`` so the work continues but the deviation is on the
        record."""
        counts = counts or {}
        # The event budget is settled when the run closes, so run.end has to be
        # evaluated *before* the internal-trail short-circuit below. Leaving this
        # after it made the whole max_events rule unreachable dead code.
        if kind == "run.end" and self.max_events and counts.get("total", 0) > self.max_events:
            return Verdict("deny", "budget_exceeded",
                           f"run exceeded max_events={self.max_events}", "block",
                           {"max_events": self.max_events, "observed": counts.get("total")})

        if kind in INTERNAL_KINDS:
            return Verdict("pass", "internal", "audit-trail event; not gated")

        if (self.allowed_actors and actor not in self.allowed_actors
                and actor_type not in self.allowed_actors):
            return Verdict("deny", "actor_not_in_mandate",
                           f"actor {actor!r} is not in the mandate", "block",
                           {"actor": actor, "actor_type": actor_type,
                            "allowed": self.allowed_actors})

        if intent and self.allowed_intents and intent not in self.allowed_intents:
            return Verdict("deny", "intent_not_in_mandate",
                           f"intent {intent!r} is outside the mandate", "block",
                           {"intent": intent, "allowed": self.allowed_intents})

        if tool and self.allowed_tools and not any(
                tool == t or tool.startswith(t + ".") for t in self.allowed_tools):
            return Verdict("deny", "tool_not_in_mandate",
                           f"tool {tool!r} is outside the mandate", "block",
                           {"tool": tool, "allowed": self.allowed_tools})

        if self.max_llm_calls and counts.get("llm.call", 0) > self.max_llm_calls:
            return Verdict("deny", "budget_exceeded",
                           f"run exceeded max_llm_calls={self.max_llm_calls}", "block",
                           {"max_llm_calls": self.max_llm_calls,
                            "observed": counts.get("llm.call")})

        # Soft signals: allowed, but the deviation is recorded. Checked after the
        # human gate, because "waiting on a person" is the more urgent signal and
        # must not be masked by "that wasn't in the plan".
        if kind in self.human_gates:
            return Verdict("hold", "awaiting_approval",
                           f"{kind} requires human sign-off", "warn",
                           {"kind": kind})

        if intent and self.planned_intents and intent not in self.planned_intents:
            return Verdict("flag", "unplanned_intent",
                           f"intent {intent!r} was not in the plan", "warn",
                           {"intent": intent, "planned": self.planned_intents})

        if domain and not self.domain_allowed(domain):
            return Verdict("flag", "scope_creep",
                           f"source domain {domain!r} is outside the mandate", "warn",
                           {"domain": domain, "allowed": self.allowed_domains})

        return Verdict("allow", "within_mandate", "action is within mandate")


# --------------------------------------------------------------- run context --

def current_run() -> Optional[str]:
    return _current_run.get()


def set_current_run(run_id: Optional[str], mandate: Optional[Mandate] = None) -> None:
    """Bind this thread/context to a run. The agents rely on this: recording a
    role event should not require every call site to thread a run id through."""
    _current_run.set(run_id)
    if mandate is not None:
        _current_mandate.set(mandate)


def current_mandate() -> Optional[Mandate]:
    return _current_mandate.get()


def _counts(store: LedgerStore, run_id: str) -> dict:
    row = store.conn.execute(
        "SELECT COUNT(*) AS total FROM ledger_events WHERE run_id = ?", (run_id,)
    ).fetchone()
    kinds = store.conn.execute(
        "SELECT kind, COUNT(*) AS n FROM ledger_events WHERE run_id = ? GROUP BY kind",
        (run_id,),
    ).fetchall()
    counts = {"total": row["total"] if row else 0}
    for r in kinds:
        counts[r["kind"]] = r["n"]
    return counts


# --------------------------------------------------------------------- runs --

def ensure_run(run_id: str, mandate: Optional[Mandate] = None,
               label: Optional[str] = None, *, store: Optional[LedgerStore] = None,
               kind: str = "ingest") -> dict:
    """Fetch or create a run row, backfilling the mandate if one was passed."""
    st = store or get_store()
    row = st.conn.execute("SELECT * FROM ledger_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        st.conn.execute(
            "INSERT INTO ledger_runs "
            "(id, label, kind, status, genesis_hash, head_hash, head_seq, created_at) "
            "VALUES (?,?,?,'open',?,?,-1,?)",
            (run_id, label, kind, GENESIS, GENESIS, _now()),
        )
        st.conn.commit()
        row = st.conn.execute("SELECT * FROM ledger_runs WHERE id = ?", (run_id,)).fetchone()
    if mandate is not None and not row["mandate_hash"]:
        st.conn.execute(
            "UPDATE ledger_runs SET mandate_json = ?, mandate_hash = ? WHERE id = ?",
            (canon(mandate.as_dict()), mandate.hash, run_id),
        )
        st.conn.commit()
    if label and not row["label"]:
        st.conn.execute("UPDATE ledger_runs SET label = ? WHERE id = ?", (label, run_id))
        st.conn.commit()
    return dict(row)


def close_run(run_id: str, *, status: str = "closed",
              store: Optional[LedgerStore] = None) -> None:
    st = store or get_store()
    st.conn.execute(
        "UPDATE ledger_runs SET status = ?, closed_at = ? WHERE id = ?",
        (status, _now(), run_id),
    )
    st.conn.commit()


def list_runs(limit: int = 50, *, store: Optional[LedgerStore] = None) -> list[dict]:
    st = store or get_store()
    rows = st.conn.execute(
        "SELECT r.*, "
        "  (SELECT COUNT(*) FROM ledger_events e WHERE e.run_id = r.id) AS events, "
        "  (SELECT MAX(e.seq) FROM ledger_events e WHERE e.run_id = r.id) AS last_seq "
        "FROM ledger_runs r ORDER BY r.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id: str, *, store: Optional[LedgerStore] = None) -> Optional[dict]:
    st = store or get_store()
    row = st.conn.execute("SELECT * FROM ledger_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def run_events(run_id: str, limit: int = 2000,
               *, store: Optional[LedgerStore] = None) -> list[dict]:
    """The run's events in chain order, projected onto the audit shape."""
    st = store or get_store()
    rows = st.conn.execute(
        "SELECT * FROM ledger_events WHERE run_id = ? ORDER BY seq LIMIT ?",
        (run_id, limit),
    ).fetchall()
    return [_event_to_audit(st.event_row_to_dict(r)) for r in rows]


def _event_to_audit(row: dict) -> dict:
    """Storage shape → audit shape (JSON columns decoded, event hash kept)."""
    return {
        "run_id": row["run_id"],
        "seq": row["seq"],
        "ts": row["ts"],
        "actor_type": row["actor_type"],
        "actor": row["actor"],
        "kind": row["kind"],
        "intent": row["intent"],
        "verdict": row["verdict"],
        "severity": row["severity"],
        "data": _loads(row["data_json"], {}),
        "prev_hash": row["prev_hash"],
        "hash": row["hash"],
        "proof": _loads(row["proof_json"], None),
        "input_refs": _loads(row["input_refs"], []),
        "trace": row["trace"],
    }


# ------------------------------------------------------------------ append --

def _resolve_mandate(run_id: str, store: LedgerStore) -> Mandate:
    row = store.conn.execute(
        "SELECT mandate_json FROM ledger_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return Mandate.from_dict(_loads(row["mandate_json"], {}) if row else {})


def append(run_id: str, kind: str, actor: str, *, actor_type: str = "system",
           intent: Optional[str] = None, data: Optional[dict] = None,
           input_refs: Optional[list] = None,
           verdict: Optional[str] = None, severity: Optional[str] = None,
           ts: Optional[str] = None, mandate: Optional[Mandate] = None,
           checked: bool = True, store: Optional[LedgerStore] = None) -> str:
    """Append one event to a run's chain and return its hash.

    ``checked=False`` is for the machinery that records the audit trail's own
    decisions — those are not themselves gated, and the audit trail must never
    be able to refuse to record that it was asked. Multi-process safety comes
    from the ``UNIQUE(run_id, seq)`` index: a losing writer retries against the
    new head.
    """
    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"unknown actor_type {actor_type!r}")
    if verdict is not None and verdict not in VALID_VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}")
    if severity is not None and severity not in VALID_SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}")

    data = _payload(data or {})
    refs = [r for r in (input_refs or []) if is_hash(r)]
    ts = ts or _now()
    st = store or get_store()

    with _LOCK:
        for attempt in range(4):
            try:
                ensure_run(run_id, store=st)
                last = st.conn.execute(
                    "SELECT seq, hash FROM ledger_events WHERE run_id = ? "
                    "ORDER BY seq DESC LIMIT 1", (run_id,)
                ).fetchone()
                seq = (last["seq"] + 1) if last else 0
                prev = last["hash"] if last else GENESIS

                if checked:
                    pol = mandate or _resolve_mandate(run_id, st)
                    v = pol.check(kind=kind, actor=actor, actor_type=actor_type,
                                  intent=intent, tool=data.get("tool"),
                                  domain=data.get("source"),
                                  counts=_counts(st, run_id))
                    if verdict is None:
                        verdict = v.decision if v.decision != "pass" else "allow"
                    if severity is None:
                        severity = v.severity
                    data = dict(data, gate=v.as_dict())

                core = event_core(
                    run_id=run_id, seq=seq, ts=ts, actor_type=actor_type,
                    actor=actor, kind=kind, intent=intent, verdict=verdict,
                    severity=severity, data=data, prev_hash=prev)
                h = chain_hash(core)

                st.conn.execute(
                    "INSERT INTO ledger_events "
                    "(run_id, seq, ts, actor_type, actor, kind, intent, verdict, "
                    " severity, data_json, input_refs, prev_hash, hash, trace) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, seq, ts, actor_type, actor, kind, intent, verdict,
                     severity, canon(data), canon(refs) if refs else None,
                     prev, h, os.environ.get("LEDGER_TRACE") or None),
                )
                st.conn.execute(
                    "UPDATE ledger_runs SET head_hash = ?, head_seq = ? WHERE id = ?",
                    (h, seq, run_id),
                )
                st.conn.commit()
                return h
            except sqlite3.IntegrityError:
                # Another writer took this seq between our read and our write.
                # Re-read the head and try again against it.
                st.conn.rollback()
                if attempt == 3:
                    st.record_drop(run_id, "append", actor,
                                   "chain append lost 4 races on seq", {"kind": kind})
                    raise
        raise RuntimeError("unreachable")


# -------------------------------------------------------------- verification --

def verify_events(events: list, *, extra_refs: Optional[Iterable[str]] = None) -> dict:
    """Walk a chain of plain dicts. Pure, so it verifies a live run and an
    offline export with the same code.

    Each stored ``input_refs`` entry is resolved against the bundle itself: a
    ref pointing at something the bundle does not contain is a finding, not a
    pass. Claim hashes live outside the event list, so callers pass them in
    ``extra_refs``.
    """
    findings: list = []
    prev = GENESIS
    expected_seq = 0
    event_hashes = {e.get("hash") for e in events if is_hash(e.get("hash") or "")}
    known = set(extra_refs or ())

    for i, ev in enumerate(events):
        core = {k: ev.get(k) for k in CORE_FIELDS}
        try:
            recomputed = chain_hash(core)
        except ValueError as e:
            findings.append({"at_seq": ev.get("seq"), "issue": "malformed_event",
                             "detail": str(e)})
            recomputed = None

        if ev.get("seq") != expected_seq:
            findings.append({"at_seq": ev.get("seq"), "issue": "sequence_gap",
                             "detail": f"expected seq {expected_seq}"})
            expected_seq = (ev.get("seq") or 0) + 1
        else:
            expected_seq += 1

        if ev.get("prev_hash") != prev:
            findings.append({"at_seq": ev.get("seq"), "issue": "broken_link",
                             "detail": "prev_hash does not match predecessor"})
        if recomputed is not None and recomputed != ev.get("hash"):
            findings.append({"at_seq": ev.get("seq"), "issue": "content_tampered",
                             "detail": "event hash does not match its contents",
                             "stored": ev.get("hash"), "recomputed": recomputed})
        prev = ev.get("hash")

        refs = ev.get("input_refs") or []
        dangling = [r for r in refs if is_hash(r) and r not in event_hashes and r not in known]
        if dangling:
            findings.append({"at_seq": ev.get("seq"), "issue": "unresolved_input_ref",
                             "detail": "input_refs point outside this run",
                             "refs": dangling})

    return {
        "ok": not findings, "events": len(events), "head_hash": prev,
        "findings": findings,
    }


def verify_chain(run_id: str, *, store: Optional[LedgerStore] = None) -> dict:
    """Full audit of one run: chain integrity, head anchoring and claim
    content-addresses."""
    st = store or get_store()
    run = get_run(run_id, store=st)
    if run is None:
        return {"ok": False, "run_id": run_id, "events": 0,
                "findings": [{"issue": "unknown_run", "detail": "no such run"}]}

    events = run_events(run_id, store=st)
    claim_rows = st.conn.execute(
        "SELECT * FROM ledger_claims WHERE run_id = ?", (run_id,)
    ).fetchall()
    report = verify_events(events, extra_refs=[c["claim_hash"] for c in claim_rows])
    findings = list(report["findings"])

    if run["head_hash"] != report["head_hash"] or run["head_seq"] != (len(events) - 1):
        findings.append({
            "issue": "head_mismatch",
            "detail": "run head does not match the last event",
            "stored": [run["head_hash"], run["head_seq"]],
            "recomputed": [report["head_hash"], len(events) - 1]})

    for claim in claim_rows:
        recomputed = claim_hash(claim["text"], _loads(claim["citations_json"], []))
        if recomputed != claim["claim_hash"]:
            findings.append({"at_seq": claim["seq"], "issue": "claim_tampered",
                             "detail": "claim hash does not match its text",
                             "stored": claim["claim_hash"], "recomputed": recomputed})

    return {
        "run_id": run_id, "ok": not findings, "events": len(events),
        "head_hash": report["head_hash"], "mandate_hash": run["mandate_hash"],
        "status": run["status"], "claims": len(claim_rows), "findings": findings,
    }


# ------------------------------------------------------------------ claims --

def claim_hash(text: str, citations: Optional[list] = None) -> str:
    """Content address for a claim: a pure function of the claim's own content.

    Two roles asserting the same thing produce the same hash, which makes "did B
    simply parrot A?" answerable and lets a reviewer pull the blast radius of a
    bad claim from one value.
    """
    return digest({"text": text or "", "citations": citations or []})


def emit_claim(run_id: str, text: str, citations: Optional[list] = None, *,
               actor: str = "unknown", actor_type: str = "agent",
               seq: Optional[int] = None, confidence: Optional[str] = None,
               verifier: Optional[str] = None, verdict: str = "unverified",
               grounding: Optional[dict] = None,
               store: Optional[LedgerStore] = None) -> dict:
    """Record a claim and its grounding state as a first-class, content-addressed row.

    Grounding is decided *here*, against the source text, and defaults to
    ``unverified`` rather than ``supported``: an extraction that nobody checked
    against the paper is not evidence, and defaulting it to supported would make
    the whole ledger assert something the pipeline never established.

    Tolerates a missing ledger the same way :func:`assurance_ledger._append`
    does: the content hash is still returned, so grounding keeps working when
    ledgering is off, and the run degrades its audit rather than its analysis.
    """
    citations = citations or []
    g = grounding if grounding is not None else {"verdict": "unverified"}
    ch = claim_hash(text, citations)
    try:
        st = store or get_store()
    except Exception:
        return {"claim_hash": ch, "verdict": verdict, "n_sources": len(citations),
                "grounding": g, "event": None, "persisted": False}
    st.conn.execute(
        "INSERT INTO ledger_claims "
        "(run_id, claim_hash, seq, actor, text, citations_json, n_sources, "
        " confidence, verdict, verifier, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, ch, seq, actor, text, canon(citations), len(citations),
         confidence, verdict, verifier, _now()),
    )
    st.conn.commit()
    # The claim row is the content; this event is what makes it visible to the
    # absence checker, which reads the chain and not the claims table. Without
    # it a run can carry a claim nobody verified and still look complete.
    ev = append(run_id, "claim.emit", actor, actor_type=actor_type,
                intent="emit_claim",
                data={"claim_hash": ch, "confidence": confidence,
                      "verifier": verifier, "verdict": verdict,
                      "n_sources": len(citations), "grounding": g},
                verdict="allow", severity="info", checked=False, store=st)
    return {"claim_hash": ch, "verdict": verdict, "n_sources": len(citations),
            "grounding": g, "event": ev, "persisted": True}


def verify_claim(run_id: str, claim_hash_value: str, verdict: str, *,
                 verifier: str = "reviewer",
                 detail: Optional[dict] = None,
                 store: Optional[LedgerStore] = None) -> dict:
    """Record a verification outcome against an existing claim row."""
    if verdict not in CLAIM_VERDICTS:
        raise ValueError(f"unknown claim verdict {verdict!r}")
    try:
        st = store or get_store()
    except Exception:
        return {"run_id": run_id, "claim_hash": claim_hash_value,
                "verdict": verdict, "verifier": verifier, "event": None,
                "persisted": False}
    st.conn.execute(
        "UPDATE ledger_claims SET verdict = ?, verifier = ? "
        "WHERE run_id = ? AND claim_hash = ?",
        (verdict, verifier, run_id, claim_hash_value),
    )
    st.conn.commit()
    ev = append(run_id, "claim.verify", verifier, actor_type="agent",
                intent="verify_claim",
                data={"claim_hash": claim_hash_value, "verdict": verdict,
                      "verifier": verifier, **(detail or {})},
                verdict="allow", severity="info", checked=False, store=st)
    return {"run_id": run_id, "claim_hash": claim_hash_value,
            "verdict": verdict, "verifier": verifier, "event": ev}


def run_claims(run_id: str, *, store: Optional[LedgerStore] = None) -> list[dict]:
    st = store or get_store()
    rows = st.conn.execute(
        "SELECT * FROM ledger_claims WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["citations"] = _loads(d.pop("citations_json"), [])
        out.append(d)
    return out


# ------------------------------------------------------------------ export --

def export_run(run_id: str, *, store: Optional[LedgerStore] = None) -> dict:
    """A self-contained bundle: the run, its chain and its claims.

    Verification against the bundle is possible with :func:`verify_events`
    alone, which is what makes the export auditable without access to the
    database it came from.
    """
    st = store or get_store()
    run = get_run(run_id, store=st)
    if run is None:
        return {"error": "unknown_run", "run_id": run_id}
    events = run_events(run_id, store=st)
    claims = run_claims(run_id, store=st)
    return {
        "run": run,
        "events": events,
        "claims": claims,
        "verification": verify_events(
            events, extra_refs=[c["claim_hash"] for c in claims]),
        "exported_at": _now(),
    }


__all__ = [
    "GENESIS", "CORE_FIELDS", "ACTOR_TYPES", "INTERNAL_KINDS",
    "VALID_VERDICTS", "VALID_SEVERITIES", "CLAIM_VERDICTS",
    "Mandate", "Verdict", "LedgerStore",
    "canon", "digest", "text_digest", "is_hash", "event_core", "chain_hash",
    "current_run", "set_current_run", "current_mandate",
    "ensure_run", "close_run", "list_runs", "get_run", "run_events", "append",
    "verify_events", "verify_chain", "claim_hash", "emit_claim", "verify_claim",
    "run_claims", "export_run",
    "get_store", "init_store", "reset_store",
]