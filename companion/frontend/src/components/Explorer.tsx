import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { loadArtifact, type LoadedArtifact } from "../lib/artifactView";
import type { ArtifactNode } from "../types";

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

export function ArtifactViewer({
  loaded,
  busy,
  onClose,
}: {
  loaded: LoadedArtifact | null;
  busy: boolean;
  onClose: () => void;
}) {
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
        {busy && <p className="typing" style={{ padding: "14px" }}>loading…</p>}
        {!busy && loaded?.kind === "markdown" && (
          <div className="artifact-body md-body" dangerouslySetInnerHTML={{ __html: loaded.html ?? "" }} />
        )}
        {!busy && loaded?.kind === "image" && (
          <div className="artifact-body image-body">
            <img src={loaded.rawUrl} alt={loaded.path} />
          </div>
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
    if (!searching) return root.children;
    return root.children
      .map((c) => filterTree(c, query))
      .filter((c): c is ArtifactNode => c !== null);
  }, [root, query, searching]);

  return (
    <div className="panel">
      <h2>Vault explorer</h2>
      <input
        className="search"
        placeholder="filter files & folders…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
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
