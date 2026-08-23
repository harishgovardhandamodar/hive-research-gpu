"""Fox — the local research companion chatbot.

Fox answers questions strictly grounded in the ingested corpus (RAG index +
knowledge graph). Every mode returns citations; unsupported claims are
flagged. Modes escalate in depth:

  fast          — quick conversational answer, no retrieval
  rag           — retrieval-grounded answer with [n] citations
  thinking      — RAG + visible step-by-step reasoning trace
  deep-thinking — question decomposition, per-part retrieval, synthesis
  deep-research — iterative plan→retrieve→gap-check loop, follow-ups,
                  related-paper suggestions from the graph
  survey        — long-form survey report job (outline → sections → md file)
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .graph import KnowledgeGraph
from .llm import LLMInterface
from .rag import RAGEngine

logger = logging.getLogger(__name__)


FOX_MODES: dict[str, dict[str, str]] = {
    "fast": {
        "label": "Fast",
        "icon": "bolt",
        "description": "Quick answer from Fox's own knowledge. No corpus lookup.",
    },
    "rag": {
        "label": "RAG",
        "icon": "book",
        "description": "Grounded in your papers with [n] citations.",
    },
    "thinking": {
        "label": "Thinking",
        "icon": "brain",
        "description": "RAG + step-by-step reasoning trace you can inspect.",
    },
    "deep-thinking": {
        "label": "Deep-Thinking",
        "icon": "layers",
        "description": "Decomposes the question, retrieves per sub-question, synthesizes.",
    },
    "deep-research": {
        "label": "Deep Research",
        "icon": "telescope",
        "description": "Iterative plan → retrieve → gap-check loop with related papers.",
    },
    "survey": {
        "label": "Survey Report",
        "icon": "scroll",
        "description": "Writes a full survey-paper report on a topic to your vault.",
    },
}

CITATION_RE = re.compile(r"\[(\d{1,2})\]")

_STATUS_WORDS = (
    "status", "ingestion", "ingest", "progress", "processing",
    "queue", "jobs", "running", "downloading", "analyzing",
)


def looks_like_status_query(message: str) -> bool:
    lowered = message.lower()
    return any(w in lowered for w in _STATUS_WORDS) and len(lowered) < 120


_DIGEST_WORDS = ("new papers", "what's new", "whats new", "digest", "recent papers",
                 "latest papers", "since yesterday", "this week")


def looks_like_digest_query(message: str) -> bool:
    lowered = message.lower()
    return any(w in lowered for w in _DIGEST_WORDS) and not looks_like_status_query(message)


SYSTEM_BASE = (
    "You are Fox, a precise research companion for an AI-agents/alignment/security "
    "researcher. Be concise, technical, and concrete. Prefer specifics (numbers, "
    "datasets, method names) over vague statements."
)

GROUNDED_RULES = (
    "Answer using ONLY the numbered context excerpts provided. Cite every claim "
    "with its excerpt number like [1] or [2][5]. If the context is insufficient, "
    "say exactly what is missing instead of guessing."
)


@dataclass
class FoxJob:
    job_id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    stage: str = ""
    progress: float = 0.0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "result": self.result,
            "error": self.error,
        }


class Fox:
    def __init__(
        self,
        config: Config,
        llm: LLMInterface,
        kg: KnowledgeGraph,
        rag: RAGEngine,
    ) -> None:
        self.config = config
        self.llm = llm
        self.kg = kg
        self.rag = rag
        self.store_dir = Path(config.root_dir) / "fox"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, FoxJob] = {}
        self._jobs_lock = threading.Lock()
        # Conversation files are read-modify-write JSON; the threaded server
        # can hit them concurrently — serialize all conversation IO.
        self._conv_io_lock = threading.RLock()
        from .feedback import FeedbackStore

        self.feedback = FeedbackStore(config)

    def _reinforcement_hints(self, mode: str | None = None) -> str:
        """Past criticism distilled into instructions — the loop's memory."""
        if not self.config.feedback_auto_improve:
            return ""
        hints = self.feedback.prompt_hints(mode=mode)
        if not hints:
            return ""
        return (
            "\n\nFeedback-driven improvement instructions:\n"
            + "\n".join(hints)
            + "\nApply these corrections proactively."
        )

    def _organizer_digest(self) -> dict[str, Any]:
        """Ask the organizer for a digest; degrade gracefully when absent."""
        org = getattr(self, "organizer", None)
        try:
            if org is not None:
                d = org.daily_digest()
                topics = ", ".join(f"{t} ({n})" for t, n in list(d["topics"].items())[:6]) or "no active topics"
                return {
                    "answer": (
                        f"{d['total_new']} new papers observed recently.\n"
                        f"Topics: {topics}\nFull digest written to: {d['path']}"
                    )
                }
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("digest via organizer failed: %s", e)
        from .jobs import get_registry

        return {"answer": get_registry().human_summary()}

    # ------------------------------------------------------------------ jobs

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def _start_job(self, kind: str) -> FoxJob:
        job = FoxJob(job_id=uuid.uuid4().hex[:12], kind=kind)
        with self._jobs_lock:
            self._jobs[job.job_id] = job
        return job

    def _run_survey_job(self, job: FoxJob, topic: str, conversation_id: str | None) -> None:
        try:
            job.status = "running"
            report_path, preview = self.write_survey_report(
                topic,
                progress_cb=lambda p, stage: setattr(job, "progress", p)
                or setattr(job, "stage", stage),
            )
            job.progress = 1.0
            job.stage = "done"
            job.status = "done"
            job.result = {"report_path": str(report_path), "preview": preview}
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Survey job failed")
            job.status = "error"
            job.error = str(e)

    # ---------------------------------------------------------- conversations

    def _conv_path(self, conversation_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", conversation_id)[:40]
        return self.store_dir / f"conv_{safe}.json"

    def list_conversations(self) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self.store_dir.glob("conv_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text())
                out.append({
                    "id": data.get("id", path.stem),
                    "title": data.get("title", "(empty)")[:80],
                    "updated": data.get("updated", ""),
                    "messages": len(data.get("messages", [])),
                })
            except Exception:
                continue
        return out

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        path = self._conv_path(conversation_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def clear_conversation(self, conversation_id: str) -> bool:
        path = self._conv_path(conversation_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def _save_conversation(self, conv: dict[str, Any]) -> None:
        with self._conv_io_lock:
            conv["updated"] = datetime.utcnow().isoformat()
            path = self._conv_path(conv["id"])
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(conv, indent=2))
            os.replace(tmp, path)

    def _append_message(self, conversation_id: str, role: str, content: str, **extra: Any) -> None:
        # Read-modify-write must be atomic or concurrent turns are lost.
        with self._conv_io_lock:
            conv = self.get_conversation(conversation_id) or {
                "id": conversation_id,
                "title": "",
                "created": datetime.utcnow().isoformat(),
                "messages": [],
            }
            if not conv["title"]:
                conv["title"] = content[:60]
            msg = {"role": role, "content": content, "ts": datetime.utcnow().isoformat()}
            msg.update(extra)
            limit = self.config.fox_history_limit * 2
            conv["messages"] = (conv["messages"] + [msg])[-limit:]
            self._save_conversation(conv)

    # -------------------------------------------------------------- retrieval

    def _retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        results = self.rag.search(query, top_k=top_k or self.config.fox_max_context_chunks)
        min_score = self.config.fox_grounding_min_score
        return [r for r in results if r["score"] >= min_score]

    def _graph_facts(self, query: str, limit: int = 6) -> list[str]:
        """Cheap lexical match of query terms against graph nodes."""
        tokens = {t for t in re.split(r"\W+", query.lower()) if len(t) > 3}
        scored: list[tuple[float, str]] = []
        for node in self.kg.concepts + self.kg.papers[:80]:
            label_tokens = set(re.split(r"\W+", node.label.lower()))
            overlap = tokens & label_tokens
            if overlap:
                score = len(overlap) / max(len(label_tokens), 1)
                definition = (getattr(node, "definition", "") or "")[:160]
                fact = f"{node.label}" + (f" — {definition}" if definition else "")
                scored.append((score, fact))
        scored.sort(key=lambda x: -x[0])
        return [fact for _, fact in scored[:limit]]

    def _build_context_block(
        self,
        chunks: list[dict[str, Any]],
        facts: list[str],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Numbered [1..n] context block + source registry."""
        sources: list[dict[str, Any]] = []
        parts: list[str] = []
        n = 0
        for f in facts:
            n += 1
            sources.append({"n": n, "kind": "graph_fact", "text": f})
            parts.append(f"[{n}] (knowledge graph) {f}")
        for c in chunks:
            n += 1
            page = c.get("page")
            sources.append({
                "n": n,
                "kind": "excerpt",
                "source_id": c["source_id"],
                "source_title": c["source_title"],
                "score": c["score"],
                "page": int(page) if page else None,
                "text": c["text"][:400],
            })
            page = c.get("page")
            page_note = f", p.{page}" if page else ""
            parts.append(f"[{n}] (paper: {c['source_title']}{page_note}, score {c['score']}) {c['text']}")
        return "\n\n".join(parts), sources

    @staticmethod
    def _extract_citations(answer: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cited_nums = {int(m) for m in CITATION_RE.findall(answer)}
        by_num = {s["n"]: s for s in sources}
        return [by_num[i] for i in sorted(cited_nums & set(by_num))]

    # ------------------------------------------------------------------- chat

    def chat(self, message: str, mode: str = "rag", conversation_id: str | None = None) -> dict[str, Any]:
        message = (message or "").strip()
        if not message:
            return {"error": "empty message"}
        mode = mode if mode in FOX_MODES else "rag"
        conversation_id = conversation_id or uuid.uuid4().hex[:12]
        started = time.time()

        self._append_message(conversation_id, "user", message, mode=mode)
        history = self.get_conversation(conversation_id)["messages"]

        if looks_like_status_query(message):
            from .jobs import get_registry

            payload = {
                "answer": "Live ingestion status:\n" + get_registry().human_summary(),
                "sources": [],
                "grounded": True,
                "kind": "status_report",
            }
        elif looks_like_digest_query(message):
            digest = self._organizer_digest()
            payload = {
                "answer": digest["answer"],
                "sources": [],
                "grounded": True,
                "kind": "digest_report",
            }
        else:
            handler = {
                "fast": self._mode_fast,
                "rag": self._mode_rag,
                "thinking": self._mode_thinking,
                "deep-thinking": self._mode_deep_thinking,
                "deep-research": self._mode_deep_research,
            }[mode]
            payload = handler(message, history)
        payload["mode"] = mode
        payload["conversation_id"] = conversation_id
        payload["elapsed_s"] = round(time.time() - started, 2)

        self._append_message(
            conversation_id,
            "assistant",
            payload.get("answer", ""),
            mode=mode,
            sources=payload.get("sources", []),
        )
        return payload

    # ---------------------------------------------------------------- modes

    def _history_text(self, history: list[dict[str, Any]], last_n: int = 6) -> str:
        turns = [
            f"{m['role']}: {m['content'][:300]}"
            for m in history[-last_n:]
            if m["role"] in ("user", "assistant") and m["content"]
        ]
        return "\n".join(turns[:-1]) if turns else ""  # exclude current question

    def _mode_fast(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = message
        hist = self._history_text(history)
        if hist:
            prompt = f"Conversation so far:\n{hist}\n\nUser: {message}"
        answer = self.llm.generate(
            prompt,
            system=SYSTEM_BASE + self._reinforcement_hints("fast"),
            temperature=self.config.fox_temperature,
        )
        return {"answer": answer.strip(), "sources": [], "grounded": False}

    def _grounded_answer(
        self,
        message: str,
        extra_instruction: str = "",
        sub_queries: list[str] | None = None,
        reasoning: bool = False,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], bool]:
        queries = [message] + (sub_queries or [])
        seen_texts: set[str] = set()
        chunks: list[dict[str, Any]] = []
        for q in queries:
            for r in self._retrieve(q):
                key = r["text"][:120]
                if key in seen_texts:
                    continue
                seen_texts.add(key)
                chunks.append(r)
        facts = self._graph_facts(message)
        context_block, sources = self._build_context_block(chunks, facts)

        if not sources:
            return (
                "I could not find anything about this in your ingested library yet. "
                "Import relevant arXiv papers first, then ask again.",
                [],
                [],
                False,
            )

        style = ""
        if reasoning:
            style = (
                "First write 'Reasoning:' followed by short numbered reasoning steps. "
                "Then write 'Answer:' with the final response.\n"
            )

        prompt_parts = [
            SYSTEM_BASE,
            GROUNDED_RULES,
            extra_instruction,
        ]
        user_prompt = (
            f"{style}Context:\n{context_block}\n\nQuestion: {message}\n\nRespond now."
        )
        answer = self.llm.generate(
            user_prompt,
            system=(
                "\n".join(p for p in prompt_parts if p)
                + self._reinforcement_hints()
            ),
            temperature=self.config.fox_temperature,
        )
        cited = self._extract_citations(answer, sources)
        if not cited and sources:
            # Model skipped [n] markers; still expose provenance so the UI
            # can show which material the answer was built from.
            return answer.strip(), sources, list(sources)[:4], True
        return answer.strip(), sources, cited, True

    # --- thinking / deep-thinking / deep-research ---------------------------

    def _mode_rag(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        answer, sources, cited, grounded = self._grounded_answer(message)
        return {
            "answer": answer,
            "sources": cited,
            "all_sources": sources,
            "grounded": grounded,
        }

    def _split_reasoning(self, answer: str) -> tuple[str, str]:
        m = re.search(r"Reasoning\s*:(.*?)Answer\s*:", answer, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip(), answer[m.end():].strip()
        return "", answer.strip()

    def _mode_thinking(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        raw, sources, cited, grounded = self._grounded_answer(message, reasoning=True)
        thinking, final = self._split_reasoning(raw)
        return {
            "answer": final or raw,
            "thinking": thinking,
            "sources": cited,
            "all_sources": sources,
            "grounded": grounded,
        }

    def _decompose(self, message: str, max_sub: int = 4) -> list[str]:
        result = self.llm.extract_structured(
            f"Break this research question into up to {max_sub} focused sub-questions "
            f"that together cover it. Return JSON: {{\"sub_questions\": [\"...\"]}}\n\n"
            f"Question: {message}",
        )
        subs = result.get("sub_questions", [])
        return [str(s) for s in subs if s][:max_sub]

    def _mode_deep_thinking(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        sub_questions = self._decompose(message)
        raw, sources, cited, grounded = self._grounded_answer(
            message,
            extra_instruction=(
                f"The question was decomposed into: {json.dumps(sub_questions)}. "
                "Address each part explicitly with headers or bullets."
                if sub_questions
                else ""
            ),
            sub_queries=sub_questions,
            reasoning=True,
        )
        thinking, final = self._split_reasoning(raw)
        return {
            "answer": final or raw,
            "thinking": thinking,
            "sub_questions": sub_questions,
            "sources": cited,
            "all_sources": sources,
            "grounded": grounded,
        }

    def _mode_deep_research(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        # Round 1: plan + retrieve
        sub_queries = self._decompose(message, max_sub=5)
        raw1, sources1, cited1, grounded1 = self._grounded_answer(
            message, sub_queries=sub_queries, reasoning=True
        )
        thinking, draft = self._split_reasoning(raw1)

        # Gap check: what does the draft NOT know?
        gaps_result = self.llm.extract_structured(
            "You drafted a partial research answer. List up to 3 specific information gaps "
            "as refined arXiv-style search queries. Return JSON: {\"queries\": [\"...\"]}\n\n"
            f"Question: {message}\nDraft:\n{draft[:1500]}",
        )
        gap_queries = [str(q) for q in gaps_result.get("queries", []) if q][:3]

        # Round 2: fill gaps
        all_sources = list(sources1)
        seen_keys = {s["n"]: s for s in all_sources}
        next_n = len(all_sources)
        for gq in gap_queries:
            for r in self._retrieve(gq, top_k=3):
                key = r["text"][:120]
                if any(s.get("source_id") == r["source_id"] and s["text"] == key for s in all_sources):
                    continue
                next_n += 1
                entry = {
                    "n": next_n,
                    "kind": "excerpt",
                    "source_id": r["source_id"],
                    "source_title": r["source_title"],
                    "score": r["score"],
                    "text": r["text"][:400],
                }
                all_sources.append(entry)
                seen_keys[next_n] = entry

        # Final synthesis over everything
        context_block = "\n\n".join(
            f"[{s['n']}] ({s['kind']}: {s.get('source_title', 'graph')}) {s['text']}"
            for s in all_sources
        )
        final_prompt = (
            f"{GROUNDED_RULES}\n\nWrite a thorough research briefing on: {message}\n"
            "Structure: Key findings / Method landscape / Open problems / What your "
            "library does not yet cover. Cite as [n].\n\nContext:\n"
            f"{context_block}"
        )
        answer = self.llm.generate(
            final_prompt,
            system=SYSTEM_BASE,
            temperature=self.config.fox_temperature,
        )
        cited = self._extract_citations(answer, all_sources)

        related = self._related_papers(message)
        return {
            "answer": answer.strip(),
            "thinking": thinking,
            "sub_queries": sub_queries,
            "gap_queries": gap_queries,
            "sources": cited,
            "all_sources": all_sources,
            "related_papers": related,
            "grounded": True,
        }

    def _related_papers(self, message: str, limit: int = 5) -> list[dict[str, Any]]:
        """Papers from the KG lexically closest to the query."""
        tokens = {t for t in re.split(r"\W+", message.lower()) if len(t) > 3}
        scored = []
        for paper in self.kg.papers:
            text = f"{paper.label} {getattr(paper, 'abstract', '') or ''}".lower()
            overlap = len(tokens & set(re.split(r"\W+", text)))
            if overlap:
                scored.append((overlap, paper))
        scored.sort(key=lambda x: -x[0])
        return [
            {"id": p.id, "title": p.label}
            for _, p in scored[:limit]
        ]

    # ------------------------------------------------------------- survey job

    def start_survey(self, topic: str, conversation_id: str | None = None) -> dict[str, Any]:
        topic = (topic or "").strip()
        if not topic:
            return {"error": "missing topic"}
        job = self._start_job("survey")
        thread = threading.Thread(
            target=self._run_survey_job,
            args=(job, topic, conversation_id),
            daemon=True,
        )
        thread.start()
        return {"job_id": job.job_id, "status": "queued"}

    def write_survey_report(
        self,
        topic: str,
        progress_cb: Any = None,
    ) -> tuple[Path, str]:
        def _progress(p: float, stage: str) -> None:
            if progress_cb:
                progress_cb(p, stage)

        _progress(0.05, "planning outline")
        outline_result = self.llm.extract_structured(
            f"You are writing an academic survey report on: {topic}\n"
            "Return ONLY JSON: {\"title\": \"...\", \"sections\": [{\"heading\": \"...\", "
            "\"focus\": \"what this section covers\", \"search_hint\": \"retrieval query\"}]}. "
            "Include Abstract, 4-7 thematic sections, Challenges/Open problems, Conclusion."
        )
        title = outline_result.get("title", f"Survey: {topic}")
        sections = outline_result.get("sections", [])

        md: list[str] = [
            f"# {title}",
            "",
            f"*Generated by Fox on {datetime.utcnow().date().isoformat()} — "
            f"grounded in {self.rag.stats().get('papers', 0)} indexed papers.*",
            "",
        ]
        used_sources: dict[str, dict[str, Any]] = {}

        total = max(len(sections), 1)
        for i, sec in enumerate(sections):
            heading = sec.get("heading", f"Section {i+1}")
            hint = sec.get("search_hint") or heading
            _progress(0.1 + 0.8 * (i / total), f"writing: {heading}")

            chunks = self._retrieve(hint, top_k=6)
            context_block, sources = self._build_context_block(chunks, [])
            for s in sources:
                key = f"{s.get('source_id')}|{s['text'][:60]}"
                used_sources[key] = s

            if context_block:
                body = self.llm.generate(
                    f"{GROUNDED_RULES}\n\nWrite the '{heading}' section of a survey on "
                    f"'{topic}'. Focus: {sec.get('focus', heading)}. Use markdown with "
                    f"citations [n].\n\nContext:\n{context_block}",
                    system=SYSTEM_BASE,
                    temperature=self.config.fox_temperature,
                )
            else:
                body = (
                    f"> ⚠️ No indexed material found for this section. Import more papers "
                    f"about '{hint}' and regenerate."
                )
            md.extend([f"## {heading}", "", body.strip(), ""])

        _progress(0.95, "compiling references")
        if used_sources:
            md.extend(["## References", ""])
            for n, s in enumerate(used_sources.values(), start=1):
                sid = s.get("source_id", "")
                link = f"https://arxiv.org/abs/{sid}" if sid and sid[0].isdigit() else ""
                ref = f"- [{sid or 'graph'}] {s.get('source_title', s['text'][:60])}"
                if link:
                    ref += f" — {link}"
                md.append(ref)

        slug = re.sub(r"[^A-Za-z0-9]+", "_", topic)[:50].strip("_") or "survey"
        reports_dir = Path(self.config.vault_dir) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"{slug}_{datetime.utcnow():%Y%m%d_%H%M%S}.md"
        report_path.write_text("\n".join(md))
        _progress(1.0, "done")
        return report_path, "\n".join(md[:40])
