from __future__ import annotations

import json
import logging
import os
import platform
import re
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import requests

from .gpu import GPUManager
from .logs import get_capture
from .organizer import Organizer

logger = logging.getLogger(__name__)

HTML = Path(__file__).parent / "dashboard.html"
LANDSCAPE_HTML = Path(__file__).parent / "landscape.html"


def _json_response(
    handler: BaseHTTPRequestHandler,
    data: Any,
    status: int = 200,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode())


def _html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(html.encode())


class RouteHandler(BaseHTTPRequestHandler):
    org: Organizer = None
    gpu_mgr: GPUManager = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug(fmt, *args)

    # -- security helpers ----------------------------------------------------

    def _check_auth(self) -> bool:
        """When HIVE_TOKEN is set, every request must present it."""
        token = os.environ.get("HIVE_TOKEN", "")
        if not token:
            return True
        presented = self.headers.get("X-Hive-Token", "")
        if not presented and self.path.startswith("/api/"):
            import urllib.parse as _up

            qs = _up.parse_qs(_up.urlparse(self.path).query)
            presented = (qs.get("token") or [""])[0]
        if presented == token:
            return True
        _json_response(self, {"error": "unauthorized"}, 401)
        return False

    def _resolve_confined(self, rel_path: str) -> str | None:
        """Resolve a user-supplied path strictly inside papers/vault dirs.

        Returns the absolute path or None. Blocks absolute paths, symlink
        escapes, and any ../ traversal leaving the allowed roots.
        """
        basedirs = [
            os.path.normpath(str(self.org.config.papers_dir)),
            os.path.normpath(str(self.org.config.vault_dir)),
        ]
        candidates = [rel_path]
        stripped = rel_path[len("Notes/"):] if rel_path.startswith("Notes/") else None
        if stripped is not None:
            candidates.append(stripped)
        for cand in candidates:
            if os.path.isabs(cand):
                continue
            for base in basedirs:
                abspath = os.path.normpath(os.path.join(base, cand))
                if not abspath.startswith(base + os.sep) and abspath != base:
                    continue  # escaped the root
                if os.path.isfile(abspath):
                    return abspath
        return None

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length).decode() if length else ""

    def _parse_path(self) -> tuple[str, dict[str, str]]:
        parts = self.path.split("?", 1)
        path = parts[0].rstrip("/")
        params: dict[str, str] = {}
        if len(parts) > 1:
            for kv in parts[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    params[k] = urllib.parse.unquote(v)
        return path, params

    def _paginate(self, items: list, params: dict[str, str]) -> dict | list:
        """Wrap a list in {items,total,offset,limit} when limit/offset given."""
        try:
            offset = max(int(params.get("offset", 0)), 0)
            limit = int(params["limit"]) if "limit" in params else None
        except ValueError:
            return items
        if limit is None and not offset:
            return items
        return {
            "items": items[offset:offset + limit] if limit is not None else items[offset:],
            "total": len(items),
            "offset": offset,
            "limit": limit,
        }

    def do_GET(self) -> None:
        if not self._check_auth():
            return
        path, params = self._parse_path()
        if path == "/" or path == "" or path == "/index.html":
            self._serve_dashboard()
        elif path == "/landscape":
            self._serve_landscape()
        elif path == "/debug/graph":
            self._serve_debug_graph()
        elif path == "/api/graph":
            _json_response(self, self.org.graph_data())
        elif path == "/api/stats":
            _json_response(self, self.org.stats())
        elif path == "/api/similarity":
            paper_ids = params.get("paper_ids", None)
            algorithm = params.get("algorithm", "combined")
            if isinstance(paper_ids, str):
                paper_ids = [x.strip() for x in paper_ids.split(",") if x.strip()]
            _json_response(self, self.org.similarity(paper_ids=paper_ids, algorithm=algorithm))
        elif path == "/api/papers":
            from .pipeline import _sanitize_id
            has_lineage = set()
            for e in self.org.kg._hive.edges:
                if e.relation == "cites":
                    has_lineage.add(e.source)
            papers = []
            vault_dir = self.org.config.vault_dir
            for n in self.org.kg.papers:
                safe = _sanitize_id(n.label) or n.id
                notes_file = Path(vault_dir) / safe / "00_notes.md"
                if notes_file.exists():
                    note_path = str(notes_file)
                    note_dir = str(Path(vault_dir) / safe)
                else:
                    legacy = Path(vault_dir) / f"{safe}.md"
                    note_path = str(legacy) if legacy.exists() else ""
                    note_dir = note_path
                papers.append({
                    "id": n.id, "title": n.label,
                    "authors": (', '.join(a.name for a in n.authors) if isinstance(n.authors, list) else n.authors) or '',
                    "published": n.published, "affiliations": n.affiliations,
                    "note_path": note_path,
                    "note_dir": note_dir if Path(note_dir).exists() else "",
                    "has_lineage": n.id in has_lineage,
                    "has_extra": bool(n.definition and n.definition.startswith("{")),
                })
            _json_response(self, self._paginate(papers, params))
        elif path == "/api/papers/search":
            def _auth_str(n):
                a = n.authors
                return ', '.join(x.name for x in a) if isinstance(a, list) else (a or '')
            q = params.get("q", "").lower()
            papers = [
                {"id": n.id, "title": n.label, "authors": _auth_str(n), "published": n.published, "affiliations": n.affiliations}
                for n in self.org.kg.papers
                if not q or q in n.label.lower() or q in _auth_str(n).lower() or q in (n.affiliations or '').lower()
            ]
            _json_response(self, papers)
        elif path == "/api/concepts":
            concepts = [
                {"id": n.id, "label": n.label, "definition": n.definition}
                for n in self.org.kg.concepts
            ]
            _json_response(self, concepts)
        elif path == "/api/browse":
            papers_dir = str(self.org.config.papers_dir)
            vault_dir = str(self.org.config.vault_dir)
            tree = []
            def _scan(dirpath):
                entries = []
                try:
                    for entry in sorted(os.listdir(dirpath)):
                        full = os.path.join(dirpath, entry)
                        if os.path.isdir(full):
                            files = []
                            for root, _dirs, filenames in os.walk(full):
                                for fn in sorted(filenames):
                                    rel = os.path.relpath(os.path.join(root, fn), full)
                                    if rel.startswith("."):
                                        continue
                                    ext = os.path.splitext(fn)[1].lower()
                                    files.append({"name": rel, "ext": ext})
                            entries.append({"name": entry, "files": files})
                        else:
                            ext = os.path.splitext(entry)[1].lower()
                            if ext in (".pdf", ".md", ".txt", ".py", ".yaml", ".json", ".html", ".csv"):
                                entries.append({"name": entry, "files": [{"name": entry, "ext": ext}]})
                except Exception as exc:
                    logger.warning("Browse scan error for %s: %s", dirpath, exc)
                return entries
            try:
                tree = _scan(papers_dir)
                vault_entries = []
                for entry in sorted(os.listdir(vault_dir)):
                    full = os.path.join(vault_dir, entry)
                    if os.path.isdir(full):
                        files = []
                        for root, _dirs, filenames in os.walk(full):
                            for fn in sorted(filenames):
                                rel = os.path.relpath(os.path.join(root, fn), full)
                                if rel.startswith("."):
                                    continue
                                ext = os.path.splitext(fn)[1].lower()
                                files.append({"name": rel, "ext": ext})
                        if files:
                            vault_entries.append({"name": entry, "files": files})
                    elif entry.endswith(".md"):
                        vault_entries.append({"name": entry, "files": [{"name": entry, "ext": ".md"}]})
                if vault_entries:
                    vault_entries.sort(key=lambda e: e["name"])
                    tree.append({"name": "Notes", "files": vault_entries})
            except Exception as e:
                _json_response(self, {"error": str(e)}, 500)
                return
            _json_response(self, {"tree": tree})
        elif path == "/api/read":
            filepath = params.get("path", "")
            if not filepath:
                _json_response(self, {"error": "missing path"}, 400)
                return
            basedirs = [str(self.org.config.papers_dir), str(self.org.config.vault_dir)]
            content = None
            for basedir in basedirs:
                abspath = os.path.normpath(os.path.join(basedir, filepath))
                if abspath.startswith(os.path.normpath(basedir)) and os.path.isfile(abspath):
                    try:
                        with open(abspath, encoding="utf-8") as f:
                            content = f.read()
                        break
                    except Exception:
                        continue
            if content is None:
                if filepath.startswith("Notes/"):
                    stripped = filepath[len("Notes/"):]
                    for basedir in basedirs:
                        abspath = os.path.normpath(os.path.join(basedir, stripped))
                        if abspath.startswith(os.path.normpath(basedir)) and os.path.isfile(abspath):
                            try:
                                with open(abspath, encoding="utf-8") as f:
                                    content = f.read()
                                break
                            except Exception:
                                continue
            if content is None:
                _json_response(self, {"error": "file not found"}, 404)
                return
            _json_response(self, {"path": filepath, "content": content})
        elif path == "/api/raw":
            file_path = params.get("path", "")
            if not file_path:
                _json_response(self, {"error": "missing path"}, 400)
                return
            abspath = self._resolve_confined(file_path)
            if not abspath:
                _json_response(self, {"error": "not found"}, 404)
                return
            ext = os.path.splitext(abspath)[1].lstrip(".").lower()
            ct = {
                "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "svg": "image/svg+xml", "pdf": "application/pdf",
                "md": "text/markdown; charset=utf-8",
                "txt": "text/plain; charset=utf-8",
            }.get(ext, "application/octet-stream")
            try:
                if ext in ("png", "jpg", "jpeg", "gif", "svg", "pdf"):
                    with open(abspath, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    content = Path(abspath).read_text(encoding="utf-8")
                    _html_response(self, f"<pre style='background:#0a0e17;color:#e2e8f0;padding:20px;font-size:13px;line-height:1.7;white-space:pre-wrap'>{content}</pre>")
            except Exception as e:
                _json_response(self, {"error": str(e)}, 500)
        elif path == "/api/web/list":
            from hive_datatype import NodeType
            web_nodes = [
                {"id": n.id, "title": n.label, "url": next((l.split("URL:")[1].strip() for l in (n.definition or "").split("\n") if l.startswith("URL:")), ""), "summary": n.abstract[:200]}
                for n in self.org.kg._hive.nodes
                if n.type == "web"
            ]
            _json_response(self, web_nodes)
        elif path == "/api/ollama":
            self._handle_ollama_status()
        elif path == "/api/gpu":
            self._handle_gpu_status()
        elif path == "/api/logs":
            n = int(params.get("n", 100))
            _json_response(self, get_capture().get_recent(n))
        elif path == "/api/pool":
            data = self.org.pool.get()
            _json_response(self, data)
        elif path == "/api/pool/papers":
            papers = self.org.pool.get_observed_papers()
            _json_response(self, self._paginate(papers, params))
        elif path == "/api/pool/graph":
            graph = self.org.pool.get_pool_graph()
            _json_response(self, graph)
        elif path == "/api/pool/topics":
            topics = self.org.pool.get_topics()
            _json_response(self, {"topics": topics})
        elif path == "/api/fox/modes":
            from .fox import FOX_MODES
            _json_response(self, {"modes": FOX_MODES, "default": "rag"})
        elif path == "/api/fox/conversations":
            _json_response(self, self.org.fox.list_conversations())
        elif path.startswith("/api/fox/conversations/"):
            conv_id = path.rsplit("/", 1)[-1]
            if params.get("delete") == "1":
                removed = self.org.fox.clear_conversation(conv_id)
                _json_response(self, {"deleted": removed})
            else:
                conv = self.org.fox.get_conversation(conv_id)
                _json_response(self, conv or {"error": "not found"}, 200 if conv else 404)
        elif path.startswith("/api/fox/job/"):
            job_id = path.rsplit("/", 1)[-1]
            status = self.org.fox.job_status(job_id)
            _json_response(self, status or {"error": "not found"}, 200 if status else 404)
        elif path == "/api/feedback":
            from .feedback import FeedbackStore
            store = FeedbackStore(self.org.config)
            kind = params.get("kind", "fox")
            limit = int(params.get("limit", 100))
            _json_response(self, store.summary(kind=kind, limit=limit))
        elif path == "/api/digest":
            hours = params.get("hours")
            _json_response(self, self.org.daily_digest(hours=int(hours) if hours else None))
        elif path == "/api/jobs" or path.startswith("/api/jobs/"):
            from .jobs import get_registry

            registry = get_registry()
            if path == "/api/jobs":
                _json_response(self, {
                    "summary": registry.summary(),
                    "jobs": registry.list_jobs(
                        active_only=params.get("active") == "1",
                        kind=params.get("kind"),
                    ),
                })
            else:
                job_id = path.rsplit("/", 1)[-1]
                job = registry.get(job_id)
                _json_response(self, job.to_dict() if job else {"error": "not found"}, 200 if job else 404)
        else:
            _json_response(self, {"error": "not found"}, 404)

    def _handle_ollama_status(self) -> None:
        base = self.org.config.ollama_base_url
        model = self.org.config.ollama_model
        fast = self.org.config.ollama_fast_model
        embed = self.org.config.ollama_embed_model
        connected = False
        models = []
        try:
            r = requests.get(f"{base}/api/tags", timeout=5)
            if r.status_code == 200:
                connected = True
                models = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        _json_response(self, {
            "connected": connected,
            "base_url": base,
            "model": model,
            "fast_model": fast,
            "embed_model": embed,
            "model_available": model in models,
            "fast_available": fast in models,
            "embed_available": embed in models,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        })

    def _handle_gpu_status(self) -> None:
        if self.gpu_mgr and self.gpu_mgr._nvidia_available:
            status = self.gpu_mgr.get_status()
            _json_response(self, {
                "backend": "cuda",
                "nvidia": True,
                "device_count": status["count"],
                "devices": status["devices"],
                "platform": status["platform"],
                "processor": status["processor"],
                "python": status["python"],
            })
            return

        import subprocess
        info: dict[str, Any] = {"backend": "cpu", "nvidia": False, "details": ""}
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                info["backend"] = "cuda"
                info["nvidia"] = True
                devices = []
                for line in r.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(", ")]
                    if len(parts) >= 6:
                        devices.append({
                            "index": parts[0],
                            "name": parts[1],
                            "memory_total_mb": parts[2],
                            "memory_used_mb": parts[3],
                            "utilization_percent": parts[4],
                            "temperature_c": parts[5],
                        })
                info["devices"] = devices
                info["details"] = f"{len(devices)} NVIDIA GPU(s) detected"
        except Exception:
            info["details"] = "No GPU detected"
        _json_response(self, info)

    def _serve_debug_graph(self) -> None:
        data = self.org.graph_data()
        nodes_json = json.dumps(data)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
body{{margin:0;background:#0a0e17;overflow:hidden;font-family:sans-serif}}
#graph{{width:100vw;height:100vh}}
#info{{position:fixed;top:10px;left:10px;color:#94a3b8;font-size:12px;z-index:10;background:rgba(0,0,0,.7);padding:8px 12px;border-radius:6px}}
</style></head>
<body>
<div id="info">Loading graph...</div>
<div id="graph"></div>
<script>
const data = {nodes_json};
const info = document.getElementById('info');
info.textContent = 'Nodes: '+data.nodes.length+', Edges: '+data.links.length;
const W = window.innerWidth, H = window.innerHeight;
const svg = d3.select('#graph').append('svg').attr('width',W).attr('height',H).attr('viewBox',[0,0,W,H]);
const links = data.links.map(d=>({{...d}}));
const nodes = data.nodes.map(d=>({{...d}}));
try {{
const sim = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(links).id(d=>d.id).distance(130).strength(.3))
  .force('charge', d3.forceManyBody().strength(-250))
  .force('center', d3.forceCenter(W/2, H/2))
  .force('collision', d3.forceCollide(25));
const link = svg.append('g').selectAll('line').data(links).join('line')
  .attr('stroke','#1e3a5f').attr('stroke-width',1.2).attr('stroke-opacity',.6);
const node = svg.append('g').selectAll('g').data(nodes).join('g')
  .call(d3.drag().on('start',(e,d)=>{{if(!e.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y}})
    .on('drag',(e,d)=>{{d.fx=e.x;d.fy=e.y}})
    .on('end',(e,d)=>{{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null}}));
node.filter(d=>d.type==='paper').append('rect')
  .attr('width',14).attr('height',14).attr('x',-7).attr('y',-7).attr('rx',4)
  .attr('fill','#60a5fa').attr('stroke','#60a5fa').attr('stroke-width',2);
node.filter(d=>d.type!=='paper').append('circle')
  .attr('r',7).attr('fill','#c084fc').attr('stroke','#c084fc').attr('stroke-width',2);
node.append('text')
  .text(d=>(d.label||'').substring(0,22))
  .attr('dx',15).attr('dy',4).attr('fill','#94a3b8').attr('font-size','10px').attr('font-family','sans-serif');
sim.on('tick',()=>{{
  link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
  node.attr('transform',d=>'translate('+d.x+','+d.y+')');
}});
info.textContent += ' | OK';
}} catch(e) {{ info.textContent += ' | ERROR: '+e.message; }}
</script></body></html>"""
        _html_response(self, html)

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        path, params = self._parse_path()
        body = self._read_body()
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        from .feedback import FeedbackStore
        if path == "/api/add":
            arxiv_id = data.get("id", params.get("id", ""))
            if not arxiv_id:
                _json_response(self, {"error": "missing id"}, 400)
                return
            model_param = data.get("model", params.get("model", None))
            model = self.org.config.resolve_model(model_param)
            result = self.org.add_by_id(arxiv_id, model=model)
            _json_response(self, result)
        elif path == "/api/search":
            query = data.get("query", params.get("query", ""))
            if not query:
                _json_response(self, {"error": "missing query"}, 400)
                return
            results = self.org.search(query)
            _json_response(self, results)
        elif path == "/api/import":
            query = data.get("query", params.get("query", ""))
            if not query:
                _json_response(self, {"error": "missing query"}, 400)
                return
            model_param = data.get("model", params.get("model", None))
            model = self.org.config.resolve_model(model_param)
            results = self.org.add_by_search(query, model=model)
            _json_response(self, results)
        elif path == "/api/query":
            question = data.get("question", params.get("question", ""))
            if not question:
                _json_response(self, {"error": "missing question"}, 400)
                return
            result = self.org.query_rag(question)
            _json_response(self, result)
        elif path == "/api/lineage":
            arxiv_id = data.get("arxiv_id", params.get("arxiv_id", ""))
            if not arxiv_id:
                _json_response(self, {"error": "missing arxiv_id"}, 400)
                return
            result = self.org.fetch_lineage(arxiv_id)
            _json_response(self, result)
        elif path == "/api/web/add":
            url = data.get("url", params.get("url", ""))
            if not url:
                _json_response(self, {"error": "missing url"}, 400)
                return
            model_param = data.get("model", params.get("model", None))
            model = self.org.config.resolve_model(model_param)
            result = self.org.web.ingest(url, model=model)
            _json_response(self, result)
        elif path == "/api/similarity":
            paper_ids = data.get("paper_ids", params.get("paper_ids", None))
            algorithm = data.get("algorithm", params.get("algorithm", "combined"))
            if isinstance(paper_ids, str):
                paper_ids = [x.strip() for x in paper_ids.split(",") if x.strip()]
            _json_response(self, self.org.similarity(paper_ids=paper_ids, algorithm=algorithm))
        elif path == "/api/refresh":
            model_param = data.get("model", params.get("model", None))
            model = self.org.config.resolve_model(model_param)
            result = self.org.refresh_papers(model=model)
            _json_response(self, result)
        elif path == "/api/papers/refresh":
            paper_id = data.get("paper_id", params.get("paper_id", ""))
            if not paper_id:
                _json_response(self, {"error": "missing paper_id"}, 400)
                return
            model_param = data.get("model", params.get("model", None))
            model = self.org.config.resolve_model(model_param)
            result = self.org.refresh_paper(paper_id, model=model)
            _json_response(self, result)
        elif path == "/api/graph/detail":
            result = self.org.detail_graph()
            _json_response(self, result)
        elif path == "/api/definitions":
            result = self.org.generate_definitions()
            _json_response(self, result)
        elif path == "/api/pool/topics/add":
            name = data.get("name", "")
            query = data.get("query", "")
            if not name or not query:
                _json_response(self, {"error": "missing name or query"}, 400)
                return
            self.org.pool.add_topic(name, query)
            _json_response(self, {"status": "ok"})
        elif path == "/api/pool/topics/remove":
            name = data.get("name", "")
            if not name:
                _json_response(self, {"error": "missing name"}, 400)
                return
            self.org.pool.remove_topic(name)
            _json_response(self, {"status": "ok"})
        elif path == "/api/pool/import":
            arxiv_id = data.get("arxiv_id", "")
            if not arxiv_id:
                _json_response(self, {"error": "missing arxiv_id"}, 400)
                return
            result = self.org.add_by_id(arxiv_id)
            if result.get("status") == "added" or result.get("status") == "exists":
                self.org.pool.mark_imported(arxiv_id)
            _json_response(self, result)
        elif path == "/api/pool/import_batch":
            arxiv_ids = data.get("arxiv_ids", [])
            if not arxiv_ids:
                _json_response(self, {"error": "missing arxiv_ids"}, 400)
                return
            results = []
            for aid in arxiv_ids:
                r = self.org.add_by_id(aid)
                if r.get("status") in ("added", "exists"):
                    self.org.pool.mark_imported(aid)
                results.append({"arxiv_id": aid, "status": r.get("status")})
            _json_response(self, {"results": results})
        elif path == "/api/fox/chat":
            message = data.get("message", "")
            if not message:
                _json_response(self, {"error": "missing message"}, 400)
                return
            result = self.org.fox.chat(
                message,
                mode=data.get("mode", "rag"),
                conversation_id=data.get("conversation_id"),
            )
            if "error" in result and result["error"] == "empty message":
                _json_response(self, result, 400)
                return
            _json_response(self, result)
        elif path == "/api/fox/feedback":
            from .feedback import parse_rating

            rating = parse_rating(data.get("rating"))
            if rating == 0:
                _json_response(self, {"error": "rating must be 1-5"}, 400)
                return
            entry = FeedbackStore(self.org.config).record(
                kind="fox",
                rating=rating,
                comment=data.get("comment", ""),
                mode=data.get("mode", ""),
                conversation_id=data.get("conversation_id", ""),
            )
            _json_response(self, {"status": "ok", "entry": entry})
        elif path == "/api/fox/survey":
            topic = data.get("topic", "")
            if not topic:
                _json_response(self, {"error": "missing topic"}, 400)
                return
            result = self.org.fox.start_survey(topic, data.get("conversation_id"))
            if "error" in result:
                _json_response(self, result, 400)
                return
            _json_response(self, result)
        elif path == "/api/feedback":
            from .feedback import parse_rating

            rating = parse_rating(data.get("rating"))
            if rating == 0:
                _json_response(self, {"error": "rating must be 1-5"}, 400)
                return
            entry = FeedbackStore(self.org.config).record(
                kind=data.get("kind", "fox"),
                rating=rating,
                comment=data.get("comment", ""),
                mode=data.get("mode", ""),
                conversation_id=data.get("conversation_id", ""),
                paper_id=data.get("paper_id", ""),
            )
            _json_response(self, {"status": "ok", "entry": entry})
        elif path == "/api/improve/run":
            model_param = data.get("model", None)
            model = self.org.config.resolve_model(model_param)
            result = self.org.auto_improve_pass(model=model)
            _json_response(self, result)
        else:
            _json_response(self, {"error": "not found"}, 404)

    def _serve_dashboard(self) -> None:
        if HTML.exists():
            _html_response(self, HTML.read_text())
        else:
            _html_response(self, _inline_dashboard())

    def _serve_landscape(self) -> None:
        if LANDSCAPE_HTML.exists():
            _html_response(self, LANDSCAPE_HTML.read_text())
        else:
            _html_response(self, "<html><body><p>Landscape view not found</p></body></html>")


def run_server(
    org: Organizer,
    gpu_mgr: GPUManager | None = None,
    host: str = "127.0.0.1",
    port: int = 7777,
) -> None:
    get_capture()
    RouteHandler.org = org
    RouteHandler.gpu_mgr = gpu_mgr
    server = ThreadingHTTPServer((host, port), RouteHandler)
    server.daemon_threads = True
    logger.info("Server listening on http://%s:%d", host, port)
    if host in ("0.0.0.0", "::") and not os.environ.get("HIVE_TOKEN"):
        logger.warning(
            "Binding to all interfaces WITHOUT auth (HIVE_TOKEN unset). "
            "Anyone on this network can read files and drive the LLMs. "
            "Set HIVE_TOKEN or bind 127.0.0.1."
        )
    if gpu_mgr:
        gpu_status = gpu_mgr.get_status()
        logger.info("GPU: %d device(s) detected", gpu_status.get("count", 0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.server_close()


def _inline_dashboard() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Hive Research GPU</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0a0e17;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center;padding:20px}
.card{background:#111827;border:1px solid #1e3a5f;border-radius:10px;padding:40px;max-width:500px}
h1{color:#60a5fa;font-size:24px;margin:0 0 8px}p{color:#94a3b8;line-height:1.6;font-size:14px}
code{background:#1e293b;padding:2px 6px;border-radius:4px;font-size:13px;color:#c084fc}
</style></head><body>
<div class="card"><h1>Hive Research GPU</h1>
<p>Dashboard file not found. Run with <code>dashboard.html</code> present or use the <code>--inline</code> flag.</p></div></body></html>"""
