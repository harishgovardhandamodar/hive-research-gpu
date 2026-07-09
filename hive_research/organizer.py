from __future__ import annotations

import json
import logging
import time
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
from .exporter import to_bibtex, to_json_dump, create_backup, papers_to_csv
from .collections import CollectionStore
from .ingestion import IngestionQueue

logger = logging.getLogger(__name__)


class Organizer:
    def __init__(self, config: Config, gpu_mgr: GPUManager | None = None) -> None:
        self.config = config
        self.gpu_mgr = gpu_mgr
        self.llm = LLMInterface(config, gpu_mgr)
        self._default_kg = KnowledgeGraph(config)
        self._default_pipeline = None
        self._default_rag = None
        self._default_pool = None
        self._default_web = None
        self._default_collections = None
        self._default_ingestion = None
        # Current user context — None means default/global
        self._current_user_id: int | None = None
        self._user_instances: dict[str, dict[str, Any]] = {}
        self._refresh_progress: dict[str, Any] = {"running": False, "total": 0, "current": 0, "current_paper": "", "errors": [], "message": ""}

        if gpu_mgr and config.gpu_enabled:
            gpu_mgr.launch_ollama_instances()

    @property
    def kg(self) -> KnowledgeGraph:
        return self._get_user_instance("kg", lambda: KnowledgeGraph(self.config))

    @property
    def pipeline(self):
        return self._get_user_instance("pipeline", lambda: PaperPipeline(self.config, self.llm, self.kg, self.gpu_mgr))

    @property
    def rag(self):
        return self._get_user_instance("rag", lambda: RAGEngine(self.config, self.llm, self.kg))

    @property
    def pool(self):
        return self._get_user_instance("pool", lambda: ResearchPool(self._user_data_dir() / "pool"))

    @property
    def web(self):
        return self._get_user_instance("web", lambda: WebIngester(self.llm, self.kg))

    @property
    def collections(self):
        return self._get_user_instance("collections", lambda: CollectionStore(self._user_data_dir() / "collections.json"))

    @property
    def ingestion(self):
        return self._get_user_instance("ingestion", lambda: IngestionQueue(self.config, self.llm, self.kg, self.pipeline, self.rag, self.gpu_mgr))

    def _user_data_dir(self) -> Path:
        if self._current_user_id is not None:
            d = Path(self.config.root_dir) / f"user_{self._current_user_id}"
            d.mkdir(parents=True, exist_ok=True)
            return d
        return Path(self.config.root_dir)

    def _user_key(self) -> str:
        return str(self._current_user_id or "default")

    def _get_user_instance(self, name: str, factory):
        key = self._user_key()
        if key not in self._user_instances:
            self._user_instances[key] = {}
        cache = self._user_instances[key]
        if name not in cache:
            cache[name] = factory()
        return cache[name]

    def set_user_context(self, user_id: int | None) -> None:
        self._current_user_id = user_id

    def get_user_context(self) -> int | None:
        return self._current_user_id

    def add_by_id(self, arxiv_id: str, with_lineage: bool = False, model: str | None = None) -> dict[str, Any]:
        result = fetch_by_id_with_meta(arxiv_id)
        if result["status"] == "error":
            return result
        paper = result["paper"]
        gpu_id = self.gpu_mgr.get_next_llm_gpu() if self.gpu_mgr else None
        result = self.pipeline.process_paper(paper, gpu_id=gpu_id, model=model)
        if result["status"] == "added":
            pdf_text = ""
            pdf_path = self.config.papers_dir / f"{arxiv_id}.pdf"
            if pdf_path.exists():
                from .parser import cached_extract_text as extract_text
                pdf_text = extract_text(pdf_path)
            if pdf_text:
                n = self.rag.index_paper(arxiv_id, pdf_text)
                result["rag_chunks"] = n
        return result

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
            from .parser import cached_extract_text as extract_text
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

    def detail_graph(self) -> dict[str, Any]:
        import threading
        done = [False]
        result = [{"detailed": 0, "graph": self.kg.to_node_link()}]

        def _run():
            try:
                count = self.kg.detail_graph(self.llm)
                result[0] = {"detailed": count, "graph": self.kg.to_node_link()}
            except Exception as e:
                logger.error("detail_graph background: %s", e)
            finally:
                done[0] = True

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"status": "started", "message": "Detailing graph edges in background."}

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

    def _refresh_single(self, node: Any, model: str | None = None) -> bool:
        import json as _json
        from .parser import cached_extract_text as _cached_extract, extract_images_from_pdf
        from .pipeline import _sanitize_id

        try:
            pdf_path = self._find_pdf(node.arxiv_id)
            if not pdf_path:
                base_id = node.arxiv_id.split("v")[0] if "v" in (node.arxiv_id or "") else node.arxiv_id
                pdf_path = download_pdf(base_id, self.config.papers_dir)
            if not pdf_path or not pdf_path.exists():
                logger.warning("No PDF found for %s — skipping", node.arxiv_id)
                return False
            text = _cached_extract(pdf_path)
            if not text:
                logger.warning("No text extracted from PDF for %s — skipping", node.arxiv_id)
                return False
            logger.info("Refreshing %s — %s", node.arxiv_id, node.label[:60])

            safe_title = _sanitize_id(node.label) or node.arxiv_id
            figures_dir = Path(self.config.vault_dir) / safe_title / "figures"
            figures = extract_images_from_pdf(pdf_path, figures_dir)

            gpu_id = self.gpu_mgr.get_next_llm_gpu() if self.gpu_mgr else None
            analysis = self.pipeline._analyze_text(text, node.label, figures=figures, model=model, gpu_id=gpu_id)
            notes = analysis.get("notes", "")
            experiment = analysis.get("experiment", {})
            results = analysis.get("results", {})
            experiments_list = analysis.get("experiments", [])
            lineage_notes = analysis.get("lineage_notes", "")
            extra = _json.dumps({"notes": notes, "experiment": experiment, "results": results})
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

    def refresh_papers(self, model: str | None = None, force: bool = False) -> dict[str, Any]:
        from hive_datatype import NodeType
        import threading

        all_paper_nodes = [
            n for n in self.kg._hive.nodes if n.type == NodeType.PAPER and n.arxiv_id
        ]
        target_ids = (
            [n.arxiv_id for n in all_paper_nodes]
            if force
            else [n.arxiv_id for n in all_paper_nodes if self.notes_missing(n.arxiv_id)]
        )
        total_papers = len(all_paper_nodes)

        if not target_ids:
            msg = "All papers already have notes" if not force else "No papers to refresh"
            logger.info("%s (%d total)", msg, total_papers)
            return {"status": "done", "refreshed": 0, "total": total_papers, "missing": 0}

        logger.info("Refreshing %d/%d papers%s", len(target_ids), total_papers, " (force)" if force else " (missing only)")
        self._refresh_progress = {
            "running": True, "total": len(target_ids), "current": 0,
            "current_paper": "", "errors": [], "message": "Starting...",
        }

        def _do_refresh(m=model):
            ok_count = 0
            for idx, arxiv_id in enumerate(target_ids, 1):
                self._refresh_progress["current"] = idx
                self._refresh_progress["current_paper"] = arxiv_id
                self._refresh_progress["message"] = f"[{idx}/{len(target_ids)}] {arxiv_id}"
                n = self.kg.get_paper(arxiv_id)
                ok = n and self._refresh_single(n, model=m)
                if ok:
                    ok_count += 1
                else:
                    self._refresh_progress["errors"].append(arxiv_id)
                logger.info("Refresh [%d/%d] %s: %s", idx, len(target_ids), "OK" if ok else "FAIL", arxiv_id)
            self._refresh_progress["running"] = False
            self._refresh_progress["message"] = f"Done: {ok_count}/{len(target_ids)} papers refreshed"
            logger.info("Refresh complete: %d/%d papers updated", ok_count, len(target_ids))

        t = threading.Thread(target=_do_refresh, daemon=True)
        t.start()
        return {
            "status": "started",
            "refreshed": 0,
            "total": total_papers,
            "target": len(target_ids),
            "force": force,
            "message": f"Refreshing {len(target_ids)} papers in background.",
        }

    @property
    def refresh_progress(self) -> dict[str, Any]:
        return dict(self._refresh_progress)

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

    # ── Analysis cache ──

    def _analysis_cache_path(self) -> Path:
        return Path(self.config.root_dir) / "analysis_cache.json"

    def _load_analysis_cache(self) -> dict:
        path = self._analysis_cache_path()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"digests": {}, "help_noob": {}, "hives": [], "cross_relations": [], "similar_concepts": []}

    def _save_analysis_cache(self, cache: dict) -> None:
        path = self._analysis_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2))

    def _paper_summary(self, node: Any) -> dict:
        """Build a structured summary dict for a paper node."""
        try:
            import json as _json
            topics = []
            concepts = []
            theories = []
            for e in self.kg.edges:
                if e.source == node.id:
                    tgt = self.kg.get_concept(e.target)
                    if tgt and getattr(tgt, "is_concept", False):
                        ct = getattr(tgt, "concept_type", "") or ""
                        label = getattr(tgt, "label", "") or ""
                        definition = getattr(tgt, "definition", "") or ""
                        if ct == "tag":
                            topics.append(label)
                        elif ct == "concept" or ct == "":
                            concepts.append({"name": label, "definition": definition[:200]})
                        elif ct == "theory":
                            theories.append({"name": label, "description": definition[:200]})
            extra = {}
            if node.definition:
                try:
                    extra = _json.loads(node.definition)
                except Exception:
                    pass
            return {
                "paper_id": node.id,
                "title": node.label or node.id,
                "summary": (node.abstract or "")[:500],
                "topics": topics or extra.get("tags", []),
                "concepts": concepts or [{"name": c, "definition": ""} for c in (extra.get("tags") or [])],
                "theories": theories,
                "full_text": "",
            }
        except Exception as e:
            logger.warning("_paper_summary failed for %s: %s", getattr(node, "id", "?"), e)
            pid = getattr(node, "id", "unknown")
            return {
                "paper_id": pid,
                "title": getattr(node, "label", pid) or pid,
                "summary": "",
                "topics": [], "concepts": [], "theories": [], "full_text": "",
            }

    def digest_types(self) -> dict:
        try:
            return self.llm.DIGEST_TYPES
        except Exception:
            return {}

    def digests(self, paper_id: str, types: str = "", refresh: bool = False) -> dict:
        cache = self._load_analysis_cache()
        digests_cache = cache.setdefault("digests", {})

        node = self.kg.get_paper(paper_id)
        if not node:
            return {"error": "Paper not found"}

        requested_types = [t.strip() for t in types.split(",") if t.strip()] if types else None
        cache_key = paper_id if requested_types is None else f"{paper_id}:" + ":".join(sorted(requested_types))

        if not refresh and cache_key in digests_cache:
            return digests_cache[cache_key]

        pdf_text = self._get_pdf_text(paper_id)
        if not pdf_text:
            return {"error": "No PDF text available"}

        try:
            paper_summary = self._paper_summary(node)
            digests = self.llm.generate_digests(pdf_text, digest_types=requested_types)
        except Exception as e:
            return {"error": f"Digest generation failed: {e}"}

        digests_cache[cache_key] = digests
        self._save_analysis_cache(cache)
        return digests

    def help_noob(self, paper_id: str, refresh: bool = False) -> dict:
        cache = self._load_analysis_cache()
        help_cache = cache.setdefault("help_noob", {})

        node = self.kg.get_paper(paper_id)
        if not node:
            return {"error": "Paper not found"}

        if not refresh and paper_id in help_cache:
            return help_cache[paper_id]

        pdf_text = self._get_pdf_text(paper_id)
        if not pdf_text:
            return {"error": "No PDF text available"}

        try:
            paper_summary = self._paper_summary(node)
            help_data = self.llm.generate_help_noob(pdf_text, analysis=paper_summary)
        except Exception as e:
            return {"error": f"Help-noob generation failed: {e}"}

        help_cache[paper_id] = help_data
        self._save_analysis_cache(cache)
        return help_data

    def _get_pdf_text(self, paper_id: str) -> str:
        from .parser import cached_extract_text
        pdf_path = self.config.papers_dir / f"{paper_id}.pdf"
        if pdf_path.exists():
            return cached_extract_text(pdf_path) or ""
        base_id = paper_id.split("v")[0] if "v" in paper_id else paper_id
        import glob as _glob
        matches = sorted(_glob.glob(str(self.config.papers_dir / f"{base_id}*.pdf")))
        for m in matches:
            text = cached_extract_text(Path(m))
            if text:
                return text
        return ""

    def overlaps(self) -> dict:
        """Find shared topics/concepts across papers."""
        try:
            topic_papers: dict[str, list[str]] = {}
            concept_papers: dict[str, list[str]] = {}

            for node in self.kg.papers:
                try:
                    summary = self._paper_summary(node)
                except Exception:
                    continue
                pid = node.id
                for t in summary.get("topics", []):
                    topic_papers.setdefault(t, []).append(pid)
                for c in summary.get("concepts", []):
                    name = (c.get("name", "") or "").lower().strip()
                    if name:
                        concept_papers.setdefault(name, []).append(pid)

            overlaps = []
            for topic, pids in topic_papers.items():
                if len(pids) > 1:
                    overlaps.append({"type": "topic", "name": topic, "papers": pids, "count": len(pids)})
            for cname, pids in concept_papers.items():
                if len(pids) > 1:
                    overlaps.append({"type": "concept", "name": cname, "papers": pids, "count": len(pids)})

            cache = self._load_analysis_cache()
            return {
                "overlaps": overlaps,
                "cross_relations": cache.get("cross_relations", []),
                "similar_concepts": cache.get("similar_concepts", []),
            }
        except Exception as e:
            logger.exception("overlaps failed")
            return {"overlaps": [], "cross_relations": [], "similar_concepts": [], "error": str(e)}

    def metagraph(self) -> dict:
        """Build a hive federation view (papers grouped by hives with links)."""
        try:
            cache = self._load_analysis_cache()
            hives = cache.get("hives", [])
            if not hives:
                hives = self._build_hives()
                cache["hives"] = hives
                self._save_analysis_cache(cache)

            paper_by_id: dict[str, dict] = {}
            for node in self.kg.papers:
                paper_by_id[node.id] = self._paper_summary(node)

            paper_to_hive: dict[str, str] = {}
            hives_out: list[dict] = []
            for idx, h in enumerate(hives):
                hid = h.get("id", f"hive_{idx}")
                pids = [pid for pid in (h.get("paper_ids", []) or []) if pid in paper_by_id]
                for pid in pids:
                    paper_to_hive.setdefault(pid, hid)
                topics_set: set[str] = set()
                concepts_set: set[str] = set()
                theories_set: set[str] = set()
                for pid in pids:
                    p = paper_by_id[pid]
                    topics_set.update(p.get("topics", []))
                    concepts_set.update(c.get("name", "").lower().strip() for c in p.get("concepts", []) if c.get("name"))
                    theories_set.update(t.get("name", "").lower().strip() for t in p.get("theories", []) if t.get("name"))
                hives_out.append({
                    "id": hid,
                    "label": h.get("label", hid),
                    "paper_ids": pids,
                    "color_idx": idx % 8,
                    "topic_count": len(topics_set),
                    "concept_count": len(concepts_set),
                    "theory_count": len(theories_set),
                })

            for pid in set(paper_by_id.keys()) - set(paper_to_hive.keys()):
                paper_to_hive[pid] = "other"
            if not any(h["id"] == "other" for h in hives_out):
                unassigned = [pid for pid in paper_by_id if pid not in paper_to_hive]
                if unassigned:
                    hives_out.append({
                        "id": "other", "label": "Other Topics",
                        "paper_ids": unassigned, "color_idx": 7,
                        "topic_count": 0, "concept_count": 0, "theory_count": 0,
                    })

            papers_out = []
            for node in self.kg.papers:
                pid = node.id
                s = self._paper_summary(node)
                papers_out.append({
                    "id": pid,
                    "title": (node.label or pid)[:80],
                    "hive": paper_to_hive.get(pid, "other"),
                    "topics": s.get("topics", []),
                    "concepts": [c.get("name", "") for c in s.get("concepts", []) if c.get("name")],
                    "theories": [t.get("name", "") for t in s.get("theories", []) if t.get("name")],
                })

            links: list[dict] = []
            topic_papers: dict[str, list[str]] = {}
            concept_papers: dict[str, list[str]] = {}
            theory_papers: dict[str, list[str]] = {}
            for node in self.kg.papers:
                pid = node.id
                s = self._paper_summary(node)
                for t in s.get("topics", []):
                    topic_papers.setdefault(t, []).append(pid)
                for c in s.get("concepts", []):
                    cname = (c.get("name", "") or "").strip()
                    if cname:
                        concept_papers.setdefault(cname.lower(), []).append(pid)
                for t in s.get("theories", []):
                    tname = (t.get("name", "") or "").strip()
                    if tname:
                        theory_papers.setdefault(tname.lower(), []).append(pid)

            def add_link(src, tgt, ltype, label, weight=1.0, relation=""):
                if not src or not tgt or src == tgt:
                    return
                links.append({"source": src, "target": tgt, "type": ltype, "label": label, "weight": weight, "relation": relation})

            for name, pids in topic_papers.items():
                uniq = sorted(set(pids))
                for i in range(len(uniq)):
                    for j in range(i + 1, len(uniq)):
                        add_link(uniq[i], uniq[j], "shared_topic", name)
            for name, pids in concept_papers.items():
                uniq = sorted(set(pids))
                for i in range(len(uniq)):
                    for j in range(i + 1, len(uniq)):
                        add_link(uniq[i], uniq[j], "shared_concept", name)
            for name, pids in theory_papers.items():
                uniq = sorted(set(pids))
                for i in range(len(uniq)):
                    for j in range(i + 1, len(uniq)):
                        add_link(uniq[i], uniq[j], "shared_theory", name)

            cross_relations = cache.get("cross_relations", [])
            for cr in cross_relations:
                src_pid = self._entity_paper_id(cr.get("source_id", ""))
                tgt_pid = self._entity_paper_id(cr.get("target_id", ""))
                if src_pid and tgt_pid:
                    add_link(src_pid, tgt_pid, "cross_relation", cr.get("relation", "related_to"), relation=cr.get("relation", ""))

            similar_concepts = cache.get("similar_concepts", [])
            for sc in similar_concepts:
                src_pid = self._entity_paper_id(sc.get("source_id", ""))
                tgt_pid = self._entity_paper_id(sc.get("target_id", ""))
                sim = sc.get("similarity")
                if src_pid and tgt_pid:
                    label = f"{float(sim):.2f}" if sim is not None else "sim"
                    add_link(src_pid, tgt_pid, "similar", label, float(sim) if sim is not None else 0.8)

            summary = {
                "papers": len(papers_out), "hives": len(hives_out), "links": len(links),
                "shared_topics": sum(1 for l in links if l["type"] == "shared_topic"),
                "shared_concepts": sum(1 for l in links if l["type"] == "shared_concept"),
                "shared_theories": sum(1 for l in links if l["type"] == "shared_theory"),
                "cross_relations": sum(1 for l in links if l["type"] == "cross_relation"),
                "similar": sum(1 for l in links if l["type"] == "similar"),
            }
            return {"hives": hives_out, "papers": papers_out, "links": links, "summary": summary}
        except Exception as e:
            logger.exception("metagraph failed")
            return {"hives": [], "papers": [], "links": [], "summary": {}, "error": str(e)}

    def _build_hives(self) -> list[dict]:
        """Use LLM to categorize papers into topic-based clusters."""
        paper_data = []
        for node in self.kg.papers:
            s = self._paper_summary(node)
            paper_data.append({
                "paper_id": node.id,
                "topics": s.get("topics", []),
                "concepts": [c.get("name", "") for c in s.get("concepts", []) if c.get("name")][:8],
                "theories": [t.get("name", "") for t in s.get("theories", []) if t.get("name")][:5],
            })

        if len(paper_data) < 2:
            return [{"id": "single", "label": "All Papers", "paper_ids": [p["paper_id"] for p in paper_data]}]

        try:
            hive_data = self.llm.categorize_papers(paper_data)
            assigned = set()
            for h in hive_data:
                assigned.update(h.get("paper_ids", []))
            all_ids = {p["paper_id"] for p in paper_data}
            unassigned = all_ids - assigned
            if unassigned:
                hive_data.append({"id": "other", "label": "Other Topics", "paper_ids": list(unassigned)})
            return hive_data
        except Exception as e:
            logger.error(f"Hive categorization failed: {e}")
            return [{"id": "all", "label": "All Papers", "paper_ids": [p["paper_id"] for p in paper_data]}]

    @staticmethod
    def _entity_paper_id(entity_id: str) -> str | None:
        if not entity_id or ":" not in entity_id:
            return None
        pid = entity_id.split(":", 1)[1]
        if ":" in pid:
            pid = pid.rsplit(":", 1)[0]
        return pid or None

    # ── Export ──

    def export_bibtex(self, output_path: str | None = None) -> str:
        return to_bibtex(self.kg, output_path)

    def export_json(self, output_path: str | None = None) -> str:
        return to_json_dump(self.kg, output_path)

    def export_csv(self, output_path: str | None = None) -> str:
        return papers_to_csv(self.kg, output_path)

    def export_backup(self, output_path: str | None = None, include_pdfs: bool = True) -> str:
        return create_backup(self.config, output_path, include_pdfs=include_pdfs)
