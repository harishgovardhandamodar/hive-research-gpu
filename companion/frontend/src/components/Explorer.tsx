import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { loadArtifact, type LoadedArtifact } from "../lib/artifactView";
import type { ArtifactNode, RelatedSubgraph } from "../types";

/** Static radial mini-graph: seeds left, keywords center, related papers right. */
function RelatedGraph({ data }: { data: RelatedSubgraph }) {
  if (!data.papers.length && !data.concepts.length) return null;
  const W = 660;
  const rowH = 22;
  const papers = data.papers.slice(0, 6);
  const concepts = data.concepts.slice(0, 8);
  const seeds = data.seeds.slice(0, 2);
  const H = Math.max(papers.length, concepts.length, seeds.length) * rowH + 30;
  const seedX = 110;
  const conceptX = 330;
  const paperX = 545;
  const yPos = (i: number, n: number) => H / 2 + (i - (n - 1) / 2) * rowH;

  const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  return (
    <div className="related-block">
      <p className="artifact-label">Related in the knowledge graph</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="related-svg">
        {seeds.map((s, si) =>
          concepts.map((c, ci) => (
            <line key={`${s.id}-${c.id}`} x1={seedX + 70} y1={yPos(si, seeds.length)} x2={conceptX - 80} y2={yPos(ci, concepts.length)} stroke="rgba(240,180,41,0.25)" strokeWidth={1} />
          )),
        )}
        {concepts.map((c, ci) =>
          papers.slice(0, 3).map((p, pi) => (
            <line key={`${c.id}-${p.id}`} x1={conceptX + 80} y1={yPos(ci, concepts.length)} x2={paperX - 90} y2={yPos(pi, papers.length)} stroke="rgba(109,179,242,0.18)" strokeWidth={1} />
          )),
        )}
        {seeds.map((s, si) => {
          const y = yPos(si, seeds.length);
          return (
            <g key={s.id}>
              <circle cx={seedX} cy={y} r={7} fill="#f0b429" />
              <text x={seedX - 12} y={y + 4} textAnchor="end" className="rl-label">{clip(s.label, 26)}</text>
            </g>
          );
        })}
        {concepts.map((c, ci) => {
          const y = yPos(ci, concepts.length);
          return (
            <g key={c.id}>
              <circle cx={conceptX} cy={y} r={4.5} fill="#f0b429" opacity={0.75} />
              <text x={conceptX - 10} y={y + 4} textAnchor="end" className="rl-dim">{clip(c.label, 28)}</text>
            </g>
          );
        })}
        {papers.map((p, pi) => {
          const y = yPos(pi, papers.length);
          return (
            <g key={p.id}>
              <circle cx={paperX} cy={y} r={5} fill="#6db3f2" />
              <text x={paperX + 12} y={y + 4} className="rl-label">{clip(p.label, 34)}</text>
              <text x={paperX + 12} y={y + 16} className="rl-dim">{p.direct ? "direct edge" : `via shared concepts · ${p.score}`}</text>
            </g>
          );
        })}
      </svg>
      {data.keywords.length > 0 && (
        <div className="keyword-chips">
          {data.keywords.map((k) => (
            <span key={k} className="chip">{k}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function kindForPath(path: string): string {
  if (path.includes("/reports/") || path.includes("/digests/")) return "report";
  return "notes";
}

export function ArtifactViewer({
  loaded,
  busy,
  onClose,
}: {
  loaded: LoadedArtifact | null;
  busy: boolean;
  onClose: () => void;
}) {
  const [related, setRelated] = useState<RelatedSubgraph | null>(null);
  const [rated, setRated] = useState<number | null>(null);

  useEffect(() => {
    setRelated(null);
    setRated(null);
    if (loaded?.kind !== "markdown" || !loaded.path) return;
    let cancelled = false;
    api
      .artifactRelated(loaded.path)
      .then((r) => {
        if (!cancelled && (r.papers.length || r.concepts.length)) setRelated(r);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [loaded?.path, loaded?.kind]);

  if (!loaded && !busy) return null;
  return (
    <div className="artifact-modal" onClick={onClose}>
      <div className="artifact-box" onClick={(e) => e.stopPropagation()}>
        <div className="artifact-head">
          <code>{loaded?.path ?? "loading…"}</code>
          {loaded?.kind === "raw" && loaded.rawUrl && (
            <a className="raw-link" href={loaded.rawUrl} target="_blank" rel="noreferrer">
              open raw
            </a>
          )}
          <button onClick={onClose}>close</button>
        </div>
        <div className="artifact-actions">
          <button
            className={rated === 5 ? "ok" : ""}
            disabled={!loaded || loaded.kind !== "markdown"}
            title="useful — teach the loop"
            onClick={() => {
              if (!loaded) return;
              setRated(5);
              void api.rateArtifact(kindForPath(loaded.path), 5);
            }}
          >
            👍 helpful
          </button>
          <button
            className={rated === 2 ? "bad" : ""}
            disabled={!loaded || loaded.kind !== "markdown"}
            title="not useful — re-analysis will be guided by this"
            onClick={() => {
              if (!loaded) return;
              setRated(2);
              void api.rateArtifact(kindForPath(loaded.path), 2);
            }}
          >
            👎 not useful
          </button>
          <button
            onClick={() => {
              if (!loaded) return;
              const name = loaded.path.split("/").slice(-1)[0].replace(/\.(md|txt)$/, "");
              window.dispatchEvent(
                new CustomEvent("fox-prefill", {
                  detail: `Walk me through "${name}" — its key contributions, methods, and how it fits my library.`,
                }),
              );
            }}
          >
            💬 ask Fox about this
          </button>
        </div>
        {busy && <p className="typing" style={{ padding: "14px" }}>loading…</p>}
        {!busy && loaded?.kind === "markdown" && (
          <div className="artifact-scroll">
            <div className="artifact-body md-body" dangerouslySetInnerHTML={{ __html: loaded.html ?? "" }} />
            {related && <RelatedGraph data={related} />}
          </div>
        )}
        {!busy && loaded?.kind === "image" && (
          <div className="artifact-body image-body">
            <img src={loaded.rawUrl} alt={loaded.path} />
          </div>
        )}
        {!busy && loaded?.kind === "pdf" && (
          <iframe src={loaded.rawUrl} title={loaded.path} className="pdf-frame" />
        )}
        {!busy && loaded?.kind === "raw" && (
          <div className="artifact-body">
            <p>No inline preview for this file type.</p>
            {loaded.rawUrl && (
              <p>
                <a className="raw-link" href={loaded.rawUrl} target="_blank" rel="noreferrer">
                  open raw file
                </a>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function useArtifactOpener() {
  const [loaded, setLoaded] = useState<LoadedArtifact | null>(null);
  const [busy, setBusy] = useState(false);

  const open = async (nodeOrPath: ArtifactNode | string) => {
    const path = typeof nodeOrPath === "string" ? nodeOrPath : (nodeOrPath.path ?? "");
    if (!path || path.includes("..")) return;
    const view =
      typeof nodeOrPath === "string"
        ? "text"
        : nodeOrPath.view ?? "none";
    setBusy(true);
    try {
      setLoaded(await loadArtifact(path, view, api.artifactContent));
    } catch (err) {
      setLoaded({
        path,
        kind: "markdown",
        html: `<pre>Could not load artifact: ${err instanceof Error ? err.message : String(err)}</pre>`,
      });
    } finally {
      setBusy(false);
    }
  };

  return { loaded, setLoaded, busy, open };
}


export type SortKey = "recent" | "name";

/** Sort every directory's children by the chosen key (recency first by default). */
function sortTree(node: ArtifactNode, key: SortKey): ArtifactNode {
  if (node.type !== "dir" || !node.children) return node;
  const kids = node.children.map((c) => sortTree(c, key));
  kids.sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    if (key === "recent") return (b.mtime ?? 0) - (a.mtime ?? 0);
    return a.name.localeCompare(b.name);
  });
  return { ...node, children: kids };
}

/** Prune the tree to nodes whose name matches; dirs keep matching descendants. */
export function filterTree(node: ArtifactNode, q: string): ArtifactNode | null {
  const needle = q.trim().toLowerCase();
  if (!needle) return node;
  const selfMatch = node.name.toLowerCase().includes(needle);
  if (node.type === "file") return selfMatch ? node : null;
  const kids = (node.children ?? [])
    .map((c) => filterTree(c, q))
    .filter((c): c is ArtifactNode => c !== null);
  if (kids.length === 0 && !selfMatch) return null;
  return { ...node, children: kids };
}

function TreeRow({
  node,
  depth,
  onOpen,
  forceExpand,
}: {
  node: ArtifactNode;
  depth: number;
  onOpen: (node: ArtifactNode) => void;
  forceExpand?: boolean;
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const isOpen = forceExpand || expanded;

  if (node.type === "dir") {
    return (
      <li>
        <button
          className={`tree-row dir ${isOpen ? "open" : ""}`}
          style={{ paddingLeft: `${depth * 13 + 8}px` }}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="caret">{isOpen ? "▾" : "▸"}</span> {node.name}
        </button>
        {isOpen && (
          <ul className="tree-children">
            {(node.children ?? []).map((c) => (
              <TreeRow key={c.path ?? c.name} node={c} depth={depth + 1} onOpen={onOpen} forceExpand={forceExpand} />
            ))}
          </ul>
        )}
      </li>
    );
  }

  const cls = node.view === "image" ? "img-file" : node.view === "text" ? "md-file" : "bin-file";
  return (
    <li>
      <button
        className={`tree-row file ${cls}`}
        style={{ paddingLeft: `${depth * 13 + 8}px` }}
        onClick={() => onOpen(node)}
        title={node.path}
      >
        {node.name}
      </button>
    </li>
  );
}

export function Explorer() {
  const [root, setRoot] = useState<ArtifactNode | null>(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const { loaded, setLoaded, busy, open } = useArtifactOpener();

  const refresh = useCallback(async () => {
    try {
      setRoot(await api.explorer());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 20000);
    return () => clearInterval(t);
  }, [refresh]);

  const searching = query.trim().length > 0;
  const children = useMemo(() => {
    if (!root?.children) return [];
    const sorted = root.children.map((c) => sortTree(c, sortKey));
    if (!searching) return sorted;
    return sorted
      .map((c) => filterTree(c, query))
      .filter((c): c is ArtifactNode => c !== null);
  }, [root, query, searching, sortKey]);

  return (
    <div className="panel">
      <h2>Vault explorer</h2>
      <div className="composer-row" style={{ marginTop: 0 }}>
        <input
          className="search"
          style={{ flex: 1 }}
          placeholder="filter files & folders…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} title="sort order">
          <option value="recent">recently generated</option>
          <option value="name">name A→Z</option>
        </select>
      </div>
      <ul className="tree">
        {children.length > 0 ? (
          children.map((c) => (
            <TreeRow key={c.path ?? c.name} node={c} depth={0} onOpen={open} forceExpand={searching} />
          ))
        ) : (
          <li className="empty">{root ? `no matches for "${query}"` : "loading vault…"}</li>
        )}
      </ul>
      <ArtifactViewer loaded={loaded} busy={busy} onClose={() => setLoaded(null)} />
    </div>
  );
}
