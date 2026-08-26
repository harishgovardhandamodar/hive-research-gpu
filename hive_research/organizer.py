from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .arxiv_fetcher import PaperInfo, download_pdf, fetch_by_id, fetch_by_id_with_meta, search_arxiv
from .config import Config
from .gpu import GPUManager
from .graph import KnowledgeGraph
from .llm import LLMInterface
from .pipeline import PaperPipeline
from .pool import ResearchPool
from .rag import RAGEngine
from .similarity import paper_similarity_matrix
from .web_ingest import WebIngester

logger = logging.getLogger(__name__)

def utcnow() -> datetime:
    """Naive UTC now (datetime.utcnow() is deprecated in 3.12+)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Organizer:
    def __init__(self, config: Config, gpu_mgr: GPUManager | None = None) -> None:
        self.config = config
        self.gpu_mgr = gpu_mgr
        self.llm = LLMInterface(config, gpu_mgr)
        self.kg = KnowledgeGraph(config)
        self.pipeline = PaperPipeline(config, self.llm, self.kg, gpu_mgr)
        self.rag = RAGEngine(config, self.llm, self.kg)
        self.pool = ResearchPool(config.root_dir / "pool")
        self.web = WebIngester(self.llm, self.kg)
        from .fox import Fox
        self.fox = Fox(config, self.llm, self.kg, self.rag)
        self.fox.organizer = self  # digest + cross-subsystem access

        if gpu_mgr and config.gpu_enabled:
            gpu_mgr.launch_ollama_instances()

    def add_by_id(self, arxiv_id: str, with_lineage: bool = False, model: str | None = None) -> dict[str, Any]:
        from .jobs import get_registry

        registry = get_registry()
        job = registry.start("ingest", f"arXiv {arxiv_id}", arxiv_id=arxiv_id)
        try:
            with registry.ctx(job, "fetch"):
                result = fetch_by_id_with_meta(arxiv_id)
            if result["status"] == "error":
                return result
            paper = result["paper"]
            gpu_id = self.gpu_mgr.get_next_llm_gpu() if self.gpu_mgr else None
            # process_paper's return value is the authoritative response; the
            # fetch dict may hold non-serializable objects (PaperInfo) so we
            # never merge it into the payload.
            result = self.pipeline.process_paper(
                paper,
                gpu_id=gpu_id,
                model=model,
                progress=lambda stage, status, detail="": registry.stage(job, stage, status, detail),
            )
            if result["status"] == "added":
                pdf_pages = []
                pdf_path = self._find_pdf(arxiv_id)
                if pdf_path:
                    from .parser import extract_text_pages

                    pdf_pages = extract_text_pages(pdf_path)
                if pdf_pages:
                    with registry.ctx(job, "rag"):
                        n = self.rag.index_paper(
                            arxiv_id,
                            "\n".join(p["text"] for p in pdf_pages),
                            pages=pdf_pages,
                        )
                    result["rag_chunks"] = n
            return result
        finally:
            registry.finish(job)

    def add_by_search(self, query: str, max_results: int | None = None, model: str | None = None) -> list[dict[str, Any]]:
        mr = max_results or self.config.arxiv_max_results
        papers = search_arxiv(query, max_results=mr)
        if self.gpu_mgr and self.config.gpu_enabled and self.gpu_mgr.device_count() > 1:
            return self.pipeline.process_papers_parallel(papers, model=model)
        results = []
        for p in papers:
            r = self.add_by_id(p.arxiv_id, model=model)
            results.append(r)
        return results

    def fetch_lineage(self, arxiv_id: str) -> dict[str, Any]:
        pdf_path = self.config.papers_dir / f"{arxiv_id}.pdf"
        if not pdf_path.exists():
            return {"status": "error", "message": f"No PDF found for {arxiv_id}"}
        from .parser import extract_text
        pdf_text = extract_text(pdf_path)
        if not pdf_text:
            return {"status": "error", "message": "Could not extract text from PDF"}
        refs = self.pipeline.fetch_lineage(arxiv_id, pdf_text)
        return {"status": "ok", "arxiv_id": arxiv_id, "references": refs}

    def search(self, query: str, max_results: int | None = None) -> list[dict[str, Any]]:
        mr = max_results or self.config.arxiv_max_results
        papers = search_arxiv(query, max_results=mr)
        return [
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "authors": p.authors_str,
                "published": p.published,
                "abstract": p.abstract[:300],
                "categories": p.categories,
            }
            for p in papers
        ]

    def query_rag(self, question: str) -> dict[str, Any]:
        return self.rag.answer(question)

    def similarity(self, paper_ids: list[str] | None = None, algorithm: str = "combined") -> list[dict[str, Any]]:
        return paper_similarity_matrix(self.kg, paper_ids=paper_ids, algorithm=algorithm, llm=self.llm)

    def graph_clusters(self, algorithm: str = "combined", threshold: float = 0.35, force: bool = False) -> dict[str, Any]:
        from .clusters import get_paper_clusters

        return get_paper_clusters(self.kg, algorithm=algorithm, threshold=threshold, force=force)

    def stats(self) -> dict[str, Any]:
        stats = {
            **self.kg.stats(),
            "rag": self.rag.stats(),
        }
        if self.gpu_mgr:
            stats["gpu"] = self.gpu_mgr.get_status()
        return stats

    def graph_data(self) -> dict[str, Any]:
        return self.kg.to_node_link()

    def save_graph_snapshot(self, name: str) -> dict[str, Any]:
        return self.kg.save_snapshot(name)

    def load_graph_snapshot(self, name: str, merge: bool = False) -> dict[str, Any]:
        result = self.kg.load_snapshot(name, merge=merge)
        # keep RAG in sync when graph is replaced — simplest is to leave RAG as-is
        # (nodes may have been added/removed, but embeddings stay valid)
        return result

    def list_graph_snapshots(self) -> list[dict[str, Any]]:
        return self.kg.list_snapshots()

    def detail_graph(self) -> dict[str, Any]:
        count = self.kg.detail_graph(self.llm)
        return {"detailed": count, "graph": self.kg.to_node_link()}

    def notes_path_for(self, paper_id: str) -> str | None:
        n = self.kg.get_paper(paper_id)
        if not n:
            return None
        from .pipeline import _sanitize_id
        safe = _sanitize_id(n.label) or paper_id
        vault_dir = Path(self.config.vault_dir)
        notes_file = vault_dir / safe / "00_notes.md"
        if notes_file.exists():
            return str(notes_file)
        legacy = vault_dir / f"{safe}.md"
        return str(legacy) if legacy.exists() else None

    def _find_pdf(self, arxiv_id: str) -> Path | None:
        papers_dir = self.config.papers_dir
        exact = papers_dir / f"{arxiv_id}.pdf"
        if exact.exists():
            return exact
        base = arxiv_id.split("v")[0] if "v" in (arxiv_id or "") else arxiv_id
        import glob as _glob
        matches = sorted(_glob.glob(str(papers_dir / f"{base}*.pdf")))
        if matches:
            return Path(matches[0])
        return None

    def _refresh_single(self, node: Any, model: str | None = None, hints: list[str] | None = None) -> bool:
        import json as _json
        from .parser import extract_text, extract_images_from_pdf
        from .pipeline import _sanitize_id

        try:
            pdf_path = self._find_pdf(node.arxiv_id)
            if not pdf_path:
                base_id = node.arxiv_id.split("v")[0] if "v" in (node.arxiv_id or "") else node.arxiv_id
                pdf_path = download_pdf(base_id, self.config.papers_dir)
            if not pdf_path or not pdf_path.exists():
                logger.warning("No PDF found for %s — skipping", node.arxiv_id)
                return False
            text = extract_text(pdf_path)
            if not text:
                logger.warning("No text extracted from PDF for %s — skipping", node.arxiv_id)
                return False
            logger.info("Refreshing %s — %s", node.arxiv_id, node.label[:60])

            safe_title = _sanitize_id(node.label) or node.arxiv_id
            figures_dir = Path(self.config.vault_dir) / safe_title / "figures"
            figures = extract_images_from_pdf(pdf_path, figures_dir)

            gpu_id = self.gpu_mgr.get_next_llm_gpu() if self.gpu_mgr else None
            analysis = self.pipeline._analyze_text(text, node.label, figures=figures, model=model, gpu_id=gpu_id, hints=hints)
            notes = analysis.get("notes", "")
            experiment = analysis.get("experiment", {})
            results = analysis.get("results", {})
            experiments_list = analysis.get("experiments", [])
            lineage_notes = analysis.get("lineage_notes", "")
            extra = _json.dumps({
                "notes": notes,
                "experiment": experiment,
                "results": results,
                "limitations": analysis.get("limitations", ""),
                "tldr": analysis.get("tldr", ""),
                "reproduction": analysis.get("reproduction", {}),
            })
            node.definition = extra[:2000]
            base_id = node.arxiv_id.split("v")[0] if "v" in (node.arxiv_id or "") else node.arxiv_id
            paper_info = fetch_by_id(base_id)
            if not paper_info:
                paper_info = PaperInfo(
                    arxiv_id=base_id,
                    title=node.label,
                    authors=[],
                    published=getattr(node, 'published', ''),
                    updated='',
                    abstract=getattr(node, 'abstract', ''),
                    categories=[],
                    authors_str=getattr(node, 'authors', ''),
                    affiliations_str=getattr(node, 'affiliations', ''),
                )
            summary = analysis.get("summary", "")
            tags = analysis.get("tags", [])
            concepts_data = analysis.get("concepts", [])
            self.pipeline._write_notes_multi(
                node.arxiv_id, paper_info, summary, tags, concepts_data,
                notes=notes, experiment=experiment, results=results,
                experiments_list=experiments_list, lineage_notes=lineage_notes,
                figures=figures, safe_title=safe_title,
                limitations=analysis.get("limitations", ""),
                tldr=analysis.get("tldr", ""),
                reproduction=analysis.get("reproduction", {}),
                experiment_ideas=analysis.get("experiment_ideas", []),
            )
            self.kg.save()
            return True
        except Exception as exc:
            logger.error("Failed to refresh %s: %s", node.arxiv_id, exc, exc_info=True)
            return False

    def notes_missing(self, paper_id: str) -> bool:
        from .pipeline import _sanitize_id
        n = self.kg.get_paper(paper_id)
        if not n:
            return True
        safe = _sanitize_id(n.label) or paper_id
        notes_file = Path(self.config.vault_dir) / safe / "00_notes.md"
        if notes_file.exists():
            return False
        legacy = Path(self.config.vault_dir) / f"{safe}.md"
        if legacy.exists():
            return False
        return True

    def refresh_paper(self, paper_id: str, model: str | None = None) -> dict[str, Any]:
        import threading
        def _do(m=model):
            n = self.kg.get_paper(paper_id)
            if not n:
                logger.warning("refresh_paper: %s not found", paper_id)
                return
            ok = self._refresh_single(n, model=m)
            if ok:
                logger.info("Single paper refresh complete: %s", paper_id)
            else:
                logger.warning("refresh_paper: could not refresh %s (PDF or text issue)", paper_id)
        t = threading.Thread(target=_do, daemon=True)
        t.start()
        return {"status": "started", "paper_id": paper_id, "message": f"Refreshing {paper_id} in background."}

    def refresh_papers(self, model: str | None = None) -> dict[str, Any]:
        from hive_datatype import NodeType
        import threading

        missing_ids = [
            n.arxiv_id for n in self.kg._hive.nodes
            if n.type == NodeType.PAPER and self.notes_missing(n.arxiv_id)
        ]
        total_papers = sum(1 for n in self.kg._hive.nodes if n.type == NodeType.PAPER)

        if not missing_ids:
            logger.info("All %d papers already have notes on disk", total_papers)
            return {"status": "done", "refreshed": 0, "total": total_papers, "missing": 0}

        logger.info("Found %d/%d papers missing notes — starting refresh", len(missing_ids), total_papers)
        total_missing = len(missing_ids)
        refreshed = [0]

        def _do_refresh(m=model):
            for idx, arxiv_id in enumerate(missing_ids, 1):
                n = self.kg.get_paper(arxiv_id)
                ok = n and self._refresh_single(n, model=m)
                if ok:
                    refreshed[0] += 1
                logger.info(
                    "Refresh progress [%d/%d] %s: %s",
                    idx, total_missing, "OK" if ok else "FAIL",
                    arxiv_id,
                )
            logger.info("Refresh complete: %d/%d papers updated", refreshed[0], total_missing)

        t = threading.Thread(target=_do_refresh, daemon=True)
        t.start()
        return {
            "status": "started",
            "refreshed": 0,
            "total": total_papers,
            "missing": len(missing_ids),
            "message": f"Refreshing {len(missing_ids)} papers in background.",
        }

    def generate_definitions(self) -> dict[str, Any]:
        from hive_datatype import NodeType
        concepts_no_def = [
            n for n in self.kg._hive.nodes
            if n.type == NodeType.CONCEPT and not n.definition
        ]
        if not concepts_no_def:
            return {"status": "ok", "generated": 0}
        generated = 0
        for node in concepts_no_def:
            paper_ids = set()
            for e in self.kg._hive.edges:
                if e.source == node.id:
                    paper_ids.add(e.target)
                elif e.target == node.id:
                    paper_ids.add(e.source)
            context = ""
            for pid in list(paper_ids)[:2]:
                p = self.kg.get_paper(pid)
                if p and p.abstract:
                    context += f"\nPaper '{p.label}': {p.abstract[:500]}"
            if not context:
                continue
            prompt = (
                f"Define the concept '{node.label}' concisely in 1-2 sentences "
                f"based on these papers:\n{context}\n\n"
                'Respond with JSON: {"definition": "..."}'
            )
            gpu_id = self.gpu_mgr.get_next_llm_gpu() if self.gpu_mgr else None
            result = self.llm.extract_structured(prompt, model=self.config.ollama_fast_model, gpu_id=gpu_id)
            definition = result.get("definition", "")
            if definition:
                node.definition = definition[:200]
                generated += 1
        if generated:
            self.kg.save()
        return {"status": "ok", "generated": generated}

    # ------------------------------------------------------ reinforcement loop

    def auto_improve_pass(self, model: str | None = None) -> dict[str, Any]:
        """Close the reinforcement loop: re-analyze papers whose notes were
        rated poorly, injecting the researcher's criticism as prompt hints.

        Fox answers are improved continuously via feedback.prompt_hints();
        this pass handles the offline artifact side (vault notes).
        """
        from .feedback import FeedbackStore
        from .jobs import get_registry

        store = FeedbackStore(self.config)
        low = [
            e for e in store.low_rated(limit=self.config.feedback_reanalyze_max * 2)
            if e.get("kind") == "notes" and e.get("paper_id")
        ]
        if not low:
            return {
                "status": "nothing-to-improve",
                "message": "No low-rated paper notes found. Rate notes in Browse to train the loop.",
            }

        # Dedupe papers keeping their most recent criticism as hints.
        per_paper: dict[str, list[str]] = {}
        for e in low:
            pid = e["paper_id"]
            hints = per_paper.setdefault(pid, [])
            comment = (e.get("comment") or "").strip()
            hint = comment or "A previous analysis of this paper was rated unhelpful; be more specific and quantitative."
            if hint not in hints:
                hints.append(hint)

        registry = get_registry()
        results = []
        for pid, hints in list(per_paper.items())[: self.config.feedback_reanalyze_max]:
            node = self.kg.get_paper(pid)
            if not node:
                results.append({"paper_id": pid, "status": "not-in-graph"})
                continue
            job = registry.start("reanalyze", f"re-analyze {pid}", arxiv_id=pid)
            try:
                with registry.ctx(job, "analyze"):
                    ok = self._refresh_single(node, model=model, hints=hints)
                registry.finish(job)
                results.append({"paper_id": pid, "status": "improved" if ok else "failed", "hints": len(hints)})
            except Exception:
                registry.finish(job, error="reanalysis failed")
                results.append({"paper_id": pid, "status": "failed"})
        return {"status": "ok", "improved_pass": results}

    # ------------------------------------------------------------- daily digest

    def daily_digest(self, hours: int | None = None) -> dict[str, Any]:
        """New pool papers since the digest window, grouped by topic,
        persisted to the vault so a researcher can skim what happened."""
        from datetime import timedelta

        hours = hours or self.config.digest_hours
        cutoff = utcnow() - timedelta(hours=hours)
        by_topic: dict[str, list[dict[str, Any]]] = {}
        total_new = 0
        for p in self.pool.get_observed_papers():
            first_seen = p.get("first_seen")
            try:
                seen_at = datetime.fromisoformat(first_seen)
            except (TypeError, ValueError):
                continue
            if seen_at < cutoff:
                continue
            total_new += 1
            for topic in p.get("topics", ["unsorted"]):
                by_topic.setdefault(topic, []).append(p)

        lines = [
            f"# Research Digest — {utcnow():%Y-%m-%d %H:%M} UTC",
            "",
            f"{total_new} papers observed in the last {hours}h across {len(by_topic)} topics.",
            "",
        ]
        for topic, papers in sorted(by_topic.items()):
            lines.extend([f"## {topic} ({len(papers)})", ""])
            for p in papers:
                imported = " *(imported)*" if p.get("imported") else ""
                authors = (p.get("authors_str") or "")[:80]
                lines.append(f"### [{p['title']}]({'' if not p['arxiv_id'][0].isdigit() else 'https://arxiv.org/abs/'}{p['arxiv_id']}){imported}")
                lines.append("")
                if authors:
                    lines.append(f"*{authors}*")
                abstract = (p.get("abstract") or "")[:280]
                if abstract:
                    lines.append("")
                    lines.append(abstract + ("…" if len(p.get("abstract") or "") > 280 else ""))
                lines.append("")

        digest_dir = Path(self.config.vault_dir) / "digests"
        digest_dir.mkdir(parents=True, exist_ok=True)
        digest_path = digest_dir / f"digest_{utcnow():%Y%m%d_%H%M}.md"
        digest_path.write_text("\n".join(lines))
        return {
            "total_new": total_new,
            "topics": {t: len(ps) for t, ps in by_topic.items()},
            "path": str(digest_path),
            "preview": "\n".join(lines[:30]),
        }
