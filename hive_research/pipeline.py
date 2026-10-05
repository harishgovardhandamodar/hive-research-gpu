from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import agents as ag
from . import assurance_ledger as al
from . import ledger as lg
from .arxiv_fetcher import PaperInfo, download_pdf, fetch_by_id
from .config import Config
from .gpu import GPUManager
from .graph import KnowledgeGraph
from .llm import LLMInterface
from .parser import extract_images_from_pdf, extract_referenced_arxiv_ids, extract_sections, extract_text

logger = logging.getLogger(__name__)


def _store_ready() -> bool:
    """Whether the ledger already has a store bound to this process."""
    try:
        lg.get_store()
        return True
    except Exception:
        return False


def _min_confidence(assurance: dict[str, Any]) -> float:
    """Lowest per-claim grounding confidence for a run, defaulting to 1.0.

    This is the number written on the published note, so it is the floor, not
    the mean: one claim the verifier could not ground should not be averaged
    away by a dozen that were fine.
    """
    claims = assurance.get("claims") or []
    if not isinstance(claims, list):
        return 1.0
    scores = [float(c.get("confidence", 1.0)) for c in claims
              if isinstance(c, dict)]
    return min(scores) if scores else 1.0


def _record_deterministic_role(run_id: str, role: str, *,
                               store: Any = None,
                               detail: dict[str, Any] | None = None) -> None:
    """Write a spawn+complete pair for a role whose work needs no model.

    Their output is already on the chain as an artifact event; this is purely so
    the absence checker can tell "the parser ran and found little" from "the
    parser never ran", which are the same thing to a stream of artifact events.
    """
    spawn = al.record_swarm_event(run_id, role=role, phase="spawn",
                                  actor="orchestrator",
                                  intent=f"run_{role}", store=store)
    al.record_swarm_event(run_id, role=role, phase="complete", actor=role,
                          parent_event=spawn, completeness="complete",
                          detail=detail or {}, store=store)


def _sanitize_id(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60].strip("_")


class PaperPipeline:
    def __init__(
        self,
        config: Config,
        llm: LLMInterface,
        kg: KnowledgeGraph,
        gpu_mgr: GPUManager | None = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.kg = kg
        self.gpu_mgr = gpu_mgr

    def process_paper(self, paper: PaperInfo, gpu_id: int | None = None, model: str | None = None, progress: Any = None) -> dict[str, Any]:
        def _prog(stage: str, status: str, detail: str = "") -> None:
            if progress:
                try:
                    progress(stage, status, detail)
                except Exception:
                    pass

        paper_id = paper.arxiv_id
        existing = self.kg.get_paper(paper_id)
        if existing:
            return {"status": "exists", "paper_id": paper_id}

        node = self.kg.add_paper(
            paper_id=paper_id,
            title=paper.title,
            authors=paper.authors_str,
            published=paper.published,
            abstract=paper.abstract,
            categories=paper.categories,
            affiliations=paper.affiliations_str,
        )

        pdf_text = ""
        pdf_path = None
        figures = []
        _prog("parse", "running", "downloading PDF")
        if self.config.arxiv_download_pdf:
            pdf_path = download_pdf(paper_id, self.config.papers_dir)
            if pdf_path and pdf_path.exists():
                pdf_text = extract_text(pdf_path)
                safe_title = _sanitize_id(paper.title) or paper_id
                figures_dir = Path(self.config.vault_dir) / safe_title / "figures"
                _prog("parse", "running", f"{len(pdf_text)} chars extracted")
                figures = extract_images_from_pdf(pdf_path, figures_dir)
                _prog("parse", "done", f"{len(figures)} figures")
            else:
                _prog("parse", "skipped", "PDF unavailable, using abstract")
        else:
            _prog("parse", "skipped", "pdf download disabled")

        text_for_analysis = pdf_text or paper.abstract
        requested_model = model or self.config.ollama_model
        run_id = f"{paper_id}"
        # Provenance first: the swarm issues one call per role, and the gateway
        # may serve any of them with a different model than asked. Capture what
        # answered so the note records the writer.
        self.llm.last_served_model = ""
        _prog("analyze", "running", f"swarm analysis ({requested_model})")
        analysis, assurance = self._analyze_via_swarm(
            run_id=run_id, paper_id=paper_id, title=paper.title,
            text=text_for_analysis, figures=figures, model=model, gpu_id=gpu_id,
        )
        served_model = str(assurance.get("analyzed_by") or requested_model)
        if served_model != requested_model:
            _prog("analyze", "note",
                  f"gateway served {served_model} instead of {requested_model}")
        _prog("analyze", "done")

        concepts = analysis.get("concepts", [])
        relations = analysis.get("relations", [])
        summary = analysis.get("summary", "")
        tags = analysis.get("tags", [])
        notes = analysis.get("notes", "")
        experiment = analysis.get("experiment", {})
        results = analysis.get("results", {})
        experiments_list = analysis.get("experiments", [])
        lineage_notes = analysis.get("lineage_notes", "")

        import json as _json
        extra = _json.dumps({
            "notes": notes,
            "experiment": experiment,
            "results": results,
            "limitations": analysis.get("limitations", ""),
            "tldr": analysis.get("tldr", ""),
            "reproduction": analysis.get("reproduction", {}),
        })
        node.definition = extra[:2000]

        for tag in tags:
            tag_id = _sanitize_id(tag)
            matched = self.kg.find_similar_concept(tag)
            if matched:
                cid = matched.id
            else:
                cid = tag_id
                self.kg.add_concept(cid, tag, definition=f"A paper tagged with '{tag}'.", concept_type="tag")
            self.kg.add_edge(paper_id, cid, "related_to")

        for c in concepts:
            cid = _sanitize_id(c.get("name", "")) or _sanitize_id(c.get("label", ""))
            if not cid:
                continue
            label = c.get("name", c.get("label", cid))
            definition = c.get("definition", "")
            matched = self.kg.find_similar_concept(label)
            if matched:
                cid = matched.id
                if definition and not matched.definition:
                    matched.definition = definition
            else:
                self.kg.add_concept(
                    cid,
                    label,
                    definition=definition,
                    concept_type=c.get("type", "concept"),
                )
            rel = c.get("relation", "related_to")
            self.kg.add_edge(paper_id, cid, rel)

        for r in relations:
            raw_src = r.get("source", paper_id)
            raw_tgt = r.get("target", "")
            rel = r.get("relation", "related_to")
            if raw_src and raw_tgt:
                src = self._resolve_id(raw_src, paper_id)
                tgt = self._resolve_id(raw_tgt, paper_id)
                if src and tgt:
                    self.kg.add_edge(src, tgt, rel)
        _prog("graph", "done", f"{len(concepts)} concepts, {len(relations)} relations")
        al.record_graph_write(run_id, actor="graph-integrator", node_id=paper_id,
                              edges=len(tags) + len(concepts) + len(relations),
                              concepts=len(concepts), store=self._ledger())

        lineage_refs = []
        if pdf_text:
            _prog("lineage", "running")
            lineage_refs = self.fetch_lineage(paper_id, pdf_text, gpu_id=gpu_id)
            _prog("lineage", "done" if lineage_refs else "skipped", f"{len(lineage_refs)} refs linked")
            if lineage_refs:
                logger.info("Lineage: %d prior papers linked for %s", len(lineage_refs), paper_id)

        _prog("notes", "running")
        note_path = self._write_notes_multi(
            paper_id, paper, summary, tags, concepts,
            notes=notes, experiment=experiment, results=results,
            experiments_list=experiments_list, lineage_notes=lineage_notes,
            figures=figures,
            limitations=analysis.get("limitations", ""),
            tldr=analysis.get("tldr", ""),
            reproduction=analysis.get("reproduction", {}),
            experiment_ideas=analysis.get("experiment_ideas", []),
            analyzed_by=served_model,
            requested_model=requested_model,
        )
        self.kg.save()
        _prog("notes", "done", str(note_path) if note_path else "no note written")
        al.record_publication(
            run_id, note_path=str(note_path) if note_path else "",
            analyzed_by=served_model, requested_model=requested_model,
            confidence=_min_confidence(assurance), store=self._ledger())
        result = {
            "status": "added",
            "paper_id": paper_id,
            "concepts": len(concepts),
            "tags": len(tags),
            "relations": len(relations),
            "note_path": str(note_path) if note_path else None,
            "has_notes": bool(notes),
            "has_experiment": bool(experiments_list),
            "has_results": bool(results and isinstance(results, dict) and any(v for v in results.values())),
            "figures": len(figures),
            "gpu_id": gpu_id,
            "run_id": run_id,
            # Surfaced on the ingest result rather than buried in the ledger:
            # these three are what a researcher needs to decide whether to open
            # the note at all.
            "swarm": {
                "degraded": bool(assurance.get("degraded")),
                "roles_failed": assurance.get("roles_failed", []),
                "grounded_ratio": (assurance.get("grounding") or {}).get("grounded_ratio"),
                "policy": (assurance.get("policy") or {}).get("decision"),
            },
        }

        if lineage_refs:
            result["lineage"] = lineage_refs

        # Verify the chain we just wrote, while the run is still open. Closing the
        # run without checking it would make "integrity.check missing" the normal
        # state and hide a real break behind the same blank.
        store = self._ledger()
        chain = lg.verify_chain(run_id, store=store)
        al.record_integrity_check(
            run_id, check="chain_verify", passed=bool(chain.get("ok")),
            detail={"events": chain.get("events"),
                    "findings": chain.get("findings", [])}, store=store)
        al.record_run_end(run_id, status="done" if not assurance.get("degraded")
                          else "degraded",
                          detail={"note_path": str(note_path) if note_path else None,
                                  "roles_failed": assurance.get("roles_failed", [])},
                          store=store)
        return result

    def process_papers_parallel(self, papers: list[PaperInfo], model: str | None = None) -> list[dict[str, Any]]:
        count = len(papers)
        if count == 0:
            return []
        max_parallel = min(
            self.config.gpu_parallel_papers,
            self.gpu_mgr.device_count() if self.gpu_mgr else 1,
            count,
        )
        results: list[dict[str, Any] | None] = [None] * count

        def _process(idx: int, paper: PaperInfo) -> None:
            gpu_id = idx % max_parallel if max_parallel > 1 else None
            try:
                results[idx] = self.process_paper(paper, gpu_id=gpu_id, model=model)
            except Exception as e:
                logger.error("Parallel process for %s failed: %s", paper.arxiv_id, e)
                results[idx] = {"status": "error", "paper_id": paper.arxiv_id, "error": str(e)}

        threads = []
        for i, paper in enumerate(papers):
            t = threading.Thread(target=_process, args=(i, paper), daemon=True)
            t.start()
            threads.append(t)
            if len(threads) >= max_parallel:
                for tt in threads:
                    tt.join(timeout=600)
                threads = []

        for t in threads:
            t.join(timeout=600)

        return [r for r in results if r is not None]

    def fetch_lineage(self, paper_id: str, pdf_text: str, max_refs: int = 10, gpu_id: int | None = None) -> list[dict[str, Any]]:
        ref_ids = extract_referenced_arxiv_ids(pdf_text)
        if not ref_ids:
            return []
        fetched = []
        for i, aid in enumerate(ref_ids[:max_refs]):
            if self.kg.get_paper(aid):
                self.kg.add_edge(paper_id, aid, "cites")
                fetched.append({"arxiv_id": aid, "status": "exists"})
                continue
            if i > 0:
                time.sleep(3)
            prior = fetch_by_id(aid)
            if prior is None:
                continue
            self.kg.add_paper(
                paper_id=aid,
                title=prior.title,
                authors=prior.authors_str,
                published=prior.published,
                abstract=prior.abstract,
                categories=prior.categories,
                affiliations=prior.affiliations_str,
            )
            self.kg.add_edge(paper_id, aid, "cites")
            fetched.append({"arxiv_id": aid, "title": prior.title[:80], "status": "added"})
            logger.info("Lineage: linked prior paper %s — %s", aid, prior.title[:80])
        if fetched:
            self.kg.save()
        return fetched

    def _resolve_id(self, name: str, fallback: str) -> str:
        sid = _sanitize_id(name)
        node = self.kg.get_paper(sid) or self.kg.get_concept(sid)
        if node:
            return node.id
        for n in self.kg._hive.nodes:
            if n.label.lower() == name.lower():
                return n.id
        for n in self.kg._hive.nodes:
            if name.lower() in n.label.lower() or n.label.lower() in name.lower():
                return n.id
        return sid or fallback

    def _build_figure_context(self, figures: list[dict[str, Any]]) -> str:
        if not figures:
            return ""
        by_page: dict[int, list[str]] = {}
        for f in figures:
            by_page.setdefault(f["page"], []).append(f["filename"])
        lines = ["\nFigures available in the PDF (reference them using [FIGURE:page=N]):"]
        for p in sorted(by_page):
            lines.append(f"  Page {p}: {', '.join(by_page[p])}")
        lines.append("")
        return "\n".join(lines)

    # Section-name → selection priority for the analysis context.
    # Experiments/Results sit mid-paper; blind head-truncation loses them.
    SECTION_PRIORITY = [
        ("abstract", 1),
        ("introduction", 2),
        ("method", 2), ("approach", 2), ("architecture", 2), ("model", 3),
        ("experiment", 1), ("evaluation", 1), ("setup", 2),
        ("result", 1), ("finding", 1),
        ("discussion", 3), ("limitation", 2), ("conclusion", 3), ("ablation", 2),
    ]

    def _select_analysis_context(self, text: str, max_chars: int = 12000) -> str:
        """Pick the most analysis-relevant sections within a char budget.

        Uses heading heuristics so Experiments/Results reach the LLM even in
        long papers where naive head-truncation would drop them.
        """
        if len(text) <= max_chars:
            return text
        try:
            sections = extract_sections(text)
        except Exception:
            return text[:max_chars]
        if len(sections) < 2:
            return text[:max_chars]

        def priority(heading: str) -> int:
            h = heading.lower()
            for needle, prio in self.SECTION_PRIORITY:
                if needle in h:
                    return prio
            return 4

        # Highest-priority sections first; prio-1 (abstract/experiments/
        # results) may use the full budget, others are capped so one huge
        # low-priority section cannot starve the rest.
        scored = sorted(
            ((priority(s["heading"]), s) for s in sections),
            key=lambda t: t[0],
        )
        chosen: list[str] = []
        budget = max_chars
        for prio, sec in scored:
            body = sec.get("content") or ""
            if not body:
                continue
            allowance = budget if prio == 1 else min(budget, max_chars // 2)
            take = min(len(body), allowance)
            if take < 40:
                continue
            chosen.append(f"## {sec['heading']}\n{body[:take]}")
            budget -= take
            if budget <= 200:
                break
        if not chosen:
            return text[:max_chars]
        return "\n\n".join(chosen)

    def _analyze_via_swarm(
        self,
        *,
        run_id: str,
        paper_id: str,
        title: str,
        text: str,
        figures: list[dict[str, Any]] | None = None,
        model: str | None = None,
        gpu_id: int | None = None,
        hints: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run the contracted agents, and fall back to one prompt if they cannot finish.

        The fallback is not a hidden compatibility shim — it is the reason a
        researcher's ingest still produces something when the gateway is down.
        What matters is that it is *recorded*: ``run.degraded`` goes on the chain
        before the fallback prompt is ever sent, so a note produced this way can
        never be mistaken for one the swarm produced. Without that record the
        degradation is invisible, which is strictly worse than not having the
        fallback at all.

        Returns ``(analysis, assurance)``. The analysis keeps the shape the rest
        of the pipeline expects, so graph writes, note rendering and RAG chunking
        are unchanged.
        """
        store = self._ledger()
        mandate = ag.build_mandate(paper_id, self.config)
        graph_context = self._graph_context_for(title)
        hints = list(hints) if hints else self._pending_hints(paper_id)

        al.record_run_start(run_id, actor="orchestrator", paper_id=paper_id,
                           mandate=mandate, store=store,
                           detail={"source_kind": "full_text" if len(text) > 1500
                                   else "abstract_only_declared",
                                   "figures": len(figures or [])})
        al.record_artifact(run_id, action="acquire", actor="source-collector",
                           artifact_id=paper_id, title=title,
                           source="arxiv.org", store=store)
        al.record_artifact(run_id, action="parse", actor="document-parser",
                           artifact_id=paper_id, title=title,
                           detail={"chars": len(text),
                                   "figures": len(figures or [])},
                           store=store)
        # The acquisition and parsing roles are deterministic, but they are still
        # contracted roles: without their swarm lifecycle the absence checker sees
        # two roles that never ran and flags every run. The artifact events above
        # say what happened to the document; these say who did it and that they
        # finished.
        _record_deterministic_role(run_id, "source-collector", store=store,
                                   detail={"source": "arxiv.org",
                                           "artifact_id": paper_id})
        _record_deterministic_role(run_id, "document-parser", store=store,
                                   detail={"chars": len(text),
                                           "figures": len(figures or [])})

        degraded_reason = ""
        try:
            merged = ag.run_extraction_swarm(
                run_id=run_id, title=title, text=self._select_analysis_context(text),
                llm=self.llm, config=self.config, figures=figures or [],
                graph_context=graph_context, model=model, gpu_id=gpu_id,
                hints=hints, store=store)
        except Exception as e:
            logger.warning("Swarm analysis failed for %s: %s", paper_id, e)
            degraded_reason = f"swarm raised: {e}"
            merged = {}

        assurance = dict(merged.get("assurance") or {})
        policy = assurance.get("policy") or {}
        # A blocked gate is a reason to fall back, not a reason to abandon: the
        # single-prompt path ignores the gate, which is precisely why it is only
        # reached with the failure on the record.
        blocked = bool(policy) and not policy.get("allowed", True)
        if degraded_reason or blocked or assurance.get("roles_failed"):
            reason = degraded_reason or (
                f"policy gate blocked: {', '.join(policy.get('blocked_by', []))}"
                if blocked else
                f"roles failed: {', '.join(assurance.get('roles_failed', []))}")
            al.record_degraded(run_id, reason, actor="orchestrator",
                               fallback="single-prompt extraction",
                               store=store)
            assurance["degraded"] = True
            assurance["degradation_reason"] = reason
            if self.config.swarm_fallback_enabled:
                analysis = self._analyze_text_monolith(
                    text, title, figures=figures or [], model=model,
                    gpu_id=gpu_id, hints=hints)
                if analysis:
                    assurance["fallback"] = "single-prompt extraction"
                    return analysis, assurance

        if not merged and not degraded_reason:
            assurance["degraded"] = True
            assurance["degradation_reason"] = "swarm produced no analysis"
        analysis = {k: v for k, v in merged.items() if k != "assurance"}
        analysis.setdefault("tags", [])
        return analysis, assurance

    def _graph_context_for(self, title: str, limit: int = 12) -> str:
        """Concepts already in the graph, for the lineage tracer to reason against.

        "How does this differ from prior work" is unanswerable without knowing
        what prior work the vault holds. Cheap to supply and the only thing that
        makes that role more than a paraphrase of the paper's own intro.
        """
        try:
            matched = self.kg.find_similar_concept(title) or []
            names = [getattr(m, "label", "") or getattr(m, "id", "")
                     for m in matched[:limit]]
            return ", ".join(n for n in names if n)
        except Exception:
            return ""

    def _pending_hints(self, paper_id: str, mode: str | None = None) -> list[str]:
        """Unaddressed feedback from past ratings, fed to the contribution extractor.

        Scoped to ingest notes only when ``mode`` is given, so low ratings on
        unrelated surfaces (a rejected experiment, say) do not get handed to the
        paper-extraction prompt as if they were complaints about it.
        """
        try:
            from .feedback import FeedbackStore
            return FeedbackStore(self.config).prompt_hints(mode)
        except Exception as e:
            logger.debug("Feedback hints unavailable for %s: %s", paper_id, e)
            return []

    def _ledger(self):
        """The run's ledger store, or ``None`` when ledgering is unavailable.

        Returning ``None`` is a supported state, not an error: every recorder
        takes ``store=None`` and degrades to a no-op, so an unwritable ledger
        degrades the audit rather than the ingest. A run without an audit trail
        is worse than one with an imperfect analysis, and losing the paper
        entirely is worse than both.
        """
        if not self.config.ledger_enabled:
            return None
        try:
            if not _store_ready():
                lg.init_store(self.config.ledger_db_path)
            return lg.get_store()
        except Exception as e:
            logger.warning("Audit ledger unavailable: %s", e)
            return None

    def _analyze_text_monolith(
        self,
        text: str,
        title: str,
        figures: list[dict[str, Any]] | None = None,
        model: str | None = None,
        gpu_id: int | None = None,
        hints: list[str] | None = None,
    ) -> dict[str, Any]:
        """The pre-swarm single-prompt extractor, retained as the fallback path.

        Kept because a degraded note beats no note, not because it is good: it
        asks fifteen questions in one prompt, so a partial answer is
        indistinguishable from a thin paper. Every call to it goes through
        :meth:`_analyze_via_swarm`, which records ``run.degraded`` first.
        """
        truncated = self._select_analysis_context(text)

        fast_prompt = (
            f"Paper: {title}\n\n"
            f"{truncated[:2000]}\n\n"
            'Extract up to 5 key tags (short keywords) as a JSON list: {"tags": [...]}'
        )
        tags_result = self.llm.extract_structured(
            fast_prompt,
            model=self.config.ollama_fast_model,
            gpu_id=gpu_id,
        )
        tags = tags_result.get("tags", [])

        figure_context = self._build_figure_context(figures or [])

        main_prompt = (
            f"Title: {title}\n\n"
            f"{figure_context}"
            f"{truncated}\n\n"
            "Return ONLY valid JSON with these fields:\n"
            "{\n"
            '  "summary": "2-3 sentence summary covering problem, approach, and key results (include numbers)",\n'
            '  "notes": "Detailed explanation of the method, architecture, experiments, and results with specific details numbers",\n'
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
            '  "limitations": "Weaknesses, failure cases, assumptions that may not hold, and open questions",\n'
            '  "tldr": "One-sentence takeaway a researcher can quote",\n'
            '  "reproduction": {\n'
            '    "datasets": ["dataset names used"],\n'
            '    "hyperparameters": "key hyperparameters needed to reproduce",\n'
            '    "metrics": ["evaluation metrics"],\n'
            '    "compute": "hardware/training time if stated",\n'
            '    "code_url": "official code repository URL if mentioned"\n'
            "  },\n"
            '  "experiment_ideas": ["1-3 concrete follow-up experiment ideas building on this paper"],\n'
            '  "lineage_notes": "Prior work this builds on and how it differs",\n'
            '  "concepts": [{"name": "...", "definition": "...", "relation": "type"}],\n'
            '  "relations": [{"source": "...", "target": "...", "relation": "..."}]\n'
            "}"
        )
        if hints:
            main_prompt += (
                "\n\nQuality requirements from the researcher's past feedback "
                "(address all of them):\n- " + "\n- ".join(hints)
            )
        analysis = self.llm.extract_structured(main_prompt, model=model, gpu_id=gpu_id)
        analysis["tags"] = tags
        return analysis

    def _analyze_text(
        self,
        text: str,
        title: str,
        figures: list[dict[str, Any]] | None = None,
        model: str | None = None,
        gpu_id: int | None = None,
        hints: list[str] | None = None,
    ) -> dict[str, Any]:
        """Single-prompt analysis. Retained for callers that want one call.

        :meth:`process_paper` does not use this -- it runs the contracted agents
        via :meth:`_analyze_via_swarm`. Kept because it is the documented fallback
        and because dropping it would mean a degraded run has nothing to degrade
        *to*.
        """
        return self._analyze_text_monolith(
            text, title, figures=figures, model=model, gpu_id=gpu_id, hints=hints)

    def _embed_figures(
        self,
        markdown_text: str,
        figures: list[dict[str, Any]],
        relative_prefix: str = "figures/",
    ) -> str:
        if not figures:
            return markdown_text
        page_figures: dict[int, list[dict[str, Any]]] = {}
        for f in figures:
            page_figures.setdefault(f["page"], []).append(f)

        def _replace(match):
            page = int(match.group(1))
            fs = page_figures.get(page, [])
            if not fs:
                return match.group(0)
            links = "\n".join(
                f"![{f.get('caption', '').strip() or 'Figure from page ' + str(page)}]({relative_prefix}{f['filename']})"
                for f in fs
            )
            return links

        return re.sub(r"\[FIGURE:page=(\d+)\]", _replace, markdown_text)

    def _write_notes_multi(
        self,
        paper_id: str,
        paper: PaperInfo,
        summary: str,
        tags: list[str],
        concepts: list[dict[str, Any]],
        notes: str = "",
        experiment: dict[str, Any] | None = None,
        results: dict[str, Any] | None = None,
        experiments_list: list[dict[str, Any]] | None = None,
        lineage_notes: str = "",
        figures: list[dict[str, Any]] | None = None,
        safe_title: str | None = None,
        limitations: str = "",
        tldr: str = "",
        reproduction: dict[str, Any] | None = None,
        experiment_ideas: list[str] | None = None,
        analyzed_by: str = "",
        requested_model: str = "",
    ) -> Path | None:
        vault = Path(self.config.vault_dir)
        vault.mkdir(parents=True, exist_ok=True)
        safe_title = safe_title or _sanitize_id(paper.title) or paper_id
        paper_dir = vault / safe_title
        paper_dir.mkdir(parents=True, exist_ok=True)

        figures = figures or []
        figures_dir = paper_dir / "figures"
        if figures:
            figures_dir.mkdir(parents=True, exist_ok=True)
        reproduction = reproduction or {}

        note_lines: list[str] = [
            "---",
            f"arxiv_id: {paper_id}",
            f'title: "{paper.title}"',
            f'authors: "{paper.authors_str}"',
            f"published: {paper.published}",
            f"tags: [{', '.join(tags)}]",
            f"figures_count: {len(figures)}",
            f"concepts_count: {len(concepts)}",
        ]
        # Provenance. The gateway may substitute the model that did the work,
        # so both names go in the note: analyzed_by is what actually wrote
        # this file, requested_model is what the pipeline asked for. Without
        # analyzed_by, a summary written by a 3B model is indistinguishable
        # from one written by the 27B model the reader configured.
        if analyzed_by:
            note_lines.append(f"analyzed_by: {analyzed_by}")
        if requested_model:
            note_lines.append(f"requested_model: {requested_model}")
        note_lines.extend(["---", ""])

        if tldr:
            note_lines.extend([f"> **TL;DR** — {tldr}", ""])

        if summary:
            note_lines.extend(["## Summary", "", summary, ""])

        if notes:
            embedded_notes = self._embed_figures(notes, figures, relative_prefix="figures/")
            note_lines.extend(["## Notes", "", embedded_notes, ""])

        if lineage_notes:
            note_lines.extend(["## Prior Work / Research Lineage", "", lineage_notes, ""])

        if results and isinstance(results, dict):
            res_parts: list[str] = []
            mf = results.get("main_findings")
            if mf:
                if isinstance(mf, list):
                    res_parts.extend(mf)
                else:
                    res_parts.append(str(mf))
            if results.get("metrics") and isinstance(results["metrics"], dict):
                m_items = []
                for mk, mv in results["metrics"].items():
                    if mv is None or mv == "":
                        continue
                    if isinstance(mv, (list, tuple)):
                        m_items.append(f"{mk}: {', '.join(str(x) for x in mv)}")
                    else:
                        m_items.append(f"{mk}: {mv}")
                if m_items:
                    res_parts.append("Metrics: " + " | ".join(m_items))
            if res_parts:
                note_lines.extend(["## Results", ""])
                for part in res_parts:
                    note_lines.append(part)
                note_lines.append("")

        if limitations:
            note_lines.extend([
                "## Limitations & Open Questions", "",
                limitations, "",
                "**Questions to hold while reading follow-up work:**",
                "- Which assumptions here break outside the evaluated setting?",
                "- What would falsify the central claim?",
                "",
            ])

        if concepts:
            note_lines.extend(["## Concepts", ""])
            for c in concepts:
                name = c.get("name", c.get("label", ""))
                rel = c.get("relation", "")
                note_lines.append(f"- **{name}** ({rel})")
            note_lines.append("")

        repro_block = self._render_reproduction_checklist(reproduction, experiments_list or [])
        note_lines.extend(repro_block)

        if experiment_ideas:
            note_lines.extend(["## Experiment Ideas (follow-ups)", ""])
            for idea in experiment_ideas:
                note_lines.append(f"- {idea}")
            note_lines.append("")

        note_lines.extend(["## Links", "", f"- [arXiv](https://arxiv.org/abs/{paper_id})"])
        if reproduction.get("code_url"):
            note_lines.append(f"- [Official code]({reproduction['code_url']})")
        if any(c.get("definition") for c in concepts):
            note_lines.extend(["", "## Definitions", ""])
            for c in concepts:
                if c.get("definition"):
                    note_lines.append(f"- **{c.get('name', c.get('label', ''))}**: {c['definition']}")

        if figures:
            note_lines.extend(["", "## Figures", ""])
            for f in figures:
                cap = f.get("caption", "").strip()
                label = cap if cap else f['filename']
                note_lines.extend([
                    f"- **Page {f['page']}**: {label}",
                    "",
                    f"![{label}](figures/{f['filename']})",
                    "",
                ])

        safe_lines = [str(item) if not isinstance(item, str) else item for item in note_lines]
        notes_path = paper_dir / "00_notes.md"
        with open(notes_path, "w") as f:
            f.write("\n".join(safe_lines))

        if experiments_list:
            for exp in experiments_list:
                exp_path = self._write_experiment_note(
                    paper_dir, paper_id, exp, reproduction
                )
        return notes_path

    # Reproduction guidelines applied to every paper's experiment notes.
    REPRO_GUIDELINES = [
        "Re-run the official baseline code before your own modifications to validate the environment.",
        "Match dataset splits and preprocessing exactly; record any unavoidable deviation.",
        "Fix all seeds and report variance over at least 3 runs where feasible.",
        "Compare against the strongest reported baseline, not just the easiest one.",
        "Log hyperparameters verbatim from the paper before tuning anything.",
        "Evaluate with the paper's metrics protocol (same splits, same averaging).",
        "Run one ablation isolating the claimed contribution.",
    ]

    def _render_reproduction_checklist(
        self,
        reproduction: dict[str, Any],
        experiments_list: list[dict[str, Any]],
    ) -> list[str]:
        lines: list[str] = ["## Reproduction Checklist", ""]
        datasets = reproduction.get("datasets") or []
        metrics = reproduction.get("metrics") or []
        hyper = reproduction.get("hyperparameters", "")
        compute = reproduction.get("compute", "")

        lines.append("**From the paper:**")
        if datasets:
            items = datasets if isinstance(datasets, list) else [datasets]
            lines.append("- Datasets: " + ", ".join(str(d) for d in items))
        else:
            lines.append("- Datasets: _(not extracted)_")
        lines.append(f"- Key hyperparameters: {hyper or '_(not extracted)_'}")
        if metrics:
            items = metrics if isinstance(metrics, list) else [metrics]
            lines.append("- Metrics to match: " + ", ".join(str(m) for m in items))
        lines.append(f"- Compute footprint: {compute or '_(not stated)_'}")
        lines.append("")
        lines.append("**Guidelines to follow when experimenting on this paper:**")
        for g in self.REPRO_GUIDELINES:
            lines.append(f"- [ ] {g}")
        lines.append("")
        lines.append(
            f"_Per-experiment logs live next to this note as `*-00-experiment.md` "
            f"({len(experiments_list)} generated)._"
        )
        lines.append("")
        return lines

    def _write_experiment_note(
        self,
        paper_dir: Path,
        paper_id: str,
        exp: dict[str, Any],
        reproduction: dict[str, Any],
    ) -> Path | None:
        if not isinstance(exp, dict):
            return None
        exp_name = str(exp.get("name", "")).strip()
        if not exp_name:
            return None
        safe_exp = _sanitize_id(exp_name) or "experiment"
        exp_lines: list[str] = [
            "---",
            f"arxiv_id: {paper_id}",
            f'experiment: "{exp_name}"',
            "status: not-started   # not-started | in-progress | reproduced | failed-to-reproduce | extended",
            "---",
            "",
            f"# {exp_name}",
            "",
        ]
        for key in ("goal", "methodology", "dataset", "setup", "baselines"):
            val = exp.get(key, "")
            if val:
                exp_lines.extend([f"## {key.capitalize()}", "", str(val), ""])
        metrics = exp.get("metrics", {})
        if metrics and isinstance(metrics, dict):
            exp_lines.extend(["## Metrics", ""])
            for mk, mv in metrics.items():
                if mv is None or mv == "":
                    continue
                exp_lines.append(f"- **{mk}**: {mv}")
            exp_lines.append("")
        results_text = exp.get("results", "")
        if results_text:
            exp_lines.extend(["## Reported Results", "", str(results_text), ""])
        findings = exp.get("findings", "")
        if findings:
            exp_lines.extend(["## Key Findings", "", str(findings), ""])

        exp_lines.extend([
            "## My Reproduction Log", "",
            "_Fill this scaffold while reproducing. Follow the guidelines in 00_notes.md._", "",
            "- **Started**: ",
            "- **Environment**: _(python version, GPU, key library versions)_",
            "- **Commands / scripts used**:",
            "  ```bash",
            "  # git clone ... && python train.py --config ...",
            "  ```",
            "- **Deviations from the paper setup**: ",
            "- **My measured results**:",
            "",
            "| metric | paper | mine | run 2 | run 3 |",
            "|--------|-------|------|-------|-------|",
            "|        |       |      |       |       |",
            "",
            "- **Outcome**: _(reproduced / partially / failed — why)_",
            "- **Lessons learned**: ",
            "",
            "### Checklist for this experiment",
            "",
        ])
        for g in self.REPRO_GUIDELINES[:4]:
            exp_lines.append(f"- [ ] {g}")

        safe_exp_lines = [str(item) if not isinstance(item, str) else item for item in exp_lines]
        exp_path = paper_dir / f"{safe_exp}-00-experiment.md"
        with open(exp_path, "w") as f:
            f.write("\n".join(safe_exp_lines))
        return exp_path
