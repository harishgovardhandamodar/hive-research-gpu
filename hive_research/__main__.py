from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Config
from .gpu import GPUManager
from .organizer import Organizer

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_search(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    results = org.search(args.query, max_results=args.max_results)
    if not results:
        print("No results found.")
        return
    for p in results:
        print(f"\n[{p['arxiv_id']}] {p['title']}")
        print(f"    Authors: {p['authors'][:120]}")
        print(f"    Published: {p['published']}")
        print(f"    Categories: {', '.join(p['categories'])}")
        print(f"    Abstract: {p['abstract'][:200]}...")


def cmd_add(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    result = org.add_by_id(args.id, model=config.resolve_model(args.model))
    print(json.dumps(result, indent=2))


def cmd_import_search(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    results = org.add_by_search(args.query, max_results=args.max_results, model=config.resolve_model(args.model))
    print(json.dumps(results, indent=2))


def cmd_stats(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    stats = org.stats()
    print(json.dumps(stats, indent=2))


def cmd_similarity(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    sim = org.similarity()
    if not sim:
        print("No papers to compare.")
        return
    for s in sim[:10]:
        print(f"  {s['source_title'][:50]}  ↔  {s['target_title'][:50]}  = {s['score']:.3f}")


def cmd_query(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    result = org.query_rag(args.question)
    print(f"\nAnswer: {result['answer']}")
    if result.get("sources"):
        print("\nSources:")
        for s in result["sources"]:
            print(f"  [{s['id']}] {s['title']}")


def cmd_gpu_status(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    status = gpu_mgr.get_status()
    print(json.dumps(status, indent=2))


def cmd_serve(args: argparse.Namespace) -> None:
    from .server import run_server

    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    run_server(org, gpu_mgr, host=args.host, port=args.port)


def cmd_fox(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    result = org.fox.chat(args.message, mode=args.mode)
    print(f"\nFox [{result['mode']}]{'' if result.get('grounded') else ' (ungrounded)'}:")
    print(result["answer"])
    sources = result.get("sources") or []
    if sources:
        print("\nSources:")
        for i, s in enumerate(sources, start=1):
            title = s.get("source_title", "knowledge graph fact")
            sid = s.get("source_id", "")
            print(f"  [{i}] {title}" + (f" (arXiv:{sid})" if sid else ""))


def cmd_digest(args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    digest = org.daily_digest(hours=args.hours)
    print(f"{digest['total_new']} new papers across: "
          + ", ".join(f"{t} ({n})" for t, n in digest["topics"].items()))
    print(f"Digest written to {digest['path']}")


def cmd_improve(_args: argparse.Namespace) -> None:
    config = Config()
    gpu_mgr = GPUManager(config)
    org = Organizer(config, gpu_mgr)
    result = org.auto_improve_pass()
    if result.get("status") == "nothing-to-improve":
        print(result["message"])
        return
    for r in result.get("improved_pass", []):
        print(f"  {r['paper_id']}: {r['status']}")


def cmd_export(args: argparse.Namespace) -> None:
    """Zip the irreplaceable research output: vault, graph, feedback, Fox chats."""
    import shutil
    from datetime import datetime
    from pathlib import Path

    config = Config()
    root = config.root_dir
    parts = {
        "vault": config.vault_dir,
        "graph": config.graph_dir,
        "feedback": Path(config.feedback_dir) if hasattr(config, "feedback_dir") else root / "feedback",
        "fox": root / "fox",
        "rag": root / "rag",
    }
    out = Path(args.output) if args.output else (
        root / "exports" / f"hive_backup_{datetime.now():%Y%m%d_%H%M%S}"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = out.parent / f".staging_{out.stem}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    included = []
    for name, src in parts.items():
        src = Path(src)
        if not src.exists():
            continue
        dest = staging / name
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.part"))
        included.append(name)
    archive = shutil.make_archive(str(out), "zip", staging)
    shutil.rmtree(staging)
    size_mb = Path(archive).stat().st_size / 1e6
    print(f"Exported {len(included)} areas ({', '.join(included)}) -> {archive} ({size_mb:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hive Research GPU — dual RTX 5080 research knowledge base",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search arXiv")
    p_search.add_argument("query", type=str)
    p_search.add_argument("-n", "--max-results", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_add = sub.add_parser("add", help="Add paper by arXiv ID")
    p_add.add_argument("id", type=str)
    p_add.add_argument("--model", type=str, default=None,
                       help='Model to use (default: large, or "fast" for the fast model)')
    p_add.set_defaults(func=cmd_add)

    p_import_ = sub.add_parser("import", help="Search and import papers")
    p_import_.add_argument("query", type=str)
    p_import_.add_argument("-n", "--max-results", type=int, default=10)
    p_import_.add_argument("--model", type=str, default=None,
                           help='Model to use (default: large, or "fast" for the fast model)')
    p_import_.set_defaults(func=cmd_import_search)

    p_stats = sub.add_parser("stats", help="Show knowledge graph stats")
    p_stats.set_defaults(func=cmd_stats)

    p_sim = sub.add_parser("similarity", help="Paper similarity matrix")
    p_sim.set_defaults(func=cmd_similarity)

    p_query = sub.add_parser("query", help="Ask a RAG question")
    p_query.add_argument("question", type=str)
    p_query.set_defaults(func=cmd_query)

    p_gpu = sub.add_parser("gpu", help="Show GPU status")
    p_gpu.set_defaults(func=cmd_gpu_status)

    p_serve = sub.add_parser("serve", help="Start web server")
    p_serve.add_argument("--host", type=str, default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=7777)
    p_serve.set_defaults(func=cmd_serve)

    p_fox = sub.add_parser("fox", help="Ask Fox, the research companion chatbot")
    p_fox.add_argument("message", type=str)
    p_fox.add_argument(
        "--mode", type=str, default="rag",
        choices=["fast", "rag", "thinking", "deep-thinking", "deep-research"],
        help="Fox reasoning mode (survey reports are only in the dashboard)",
    )
    p_fox.set_defaults(func=cmd_fox)

    p_digest = sub.add_parser("digest", help="Write a research digest of new pool papers")
    p_digest.add_argument("--hours", type=int, default=None, help="look-back window (default: workflow.digest_hours)")
    p_digest.set_defaults(func=cmd_digest)

    p_improve = sub.add_parser("improve", help="Re-analyze papers whose notes were rated poorly")
    p_improve.set_defaults(func=cmd_improve)

    p_export = sub.add_parser("export", help="Back up vault/graph/feedback/fox to a zip archive")
    p_export.add_argument("-o", "--output", type=str, default=None,
                          help="output path without .zip (default: data/exports/hive_backup_<ts>)")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
