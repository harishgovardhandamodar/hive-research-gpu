import { useCallback, useEffect, useState } from "react";
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

function TreeRow({
  node,
  depth,
  onOpen,
}: {
  node: ArtifactNode;
  depth: number;
  onOpen: (node: ArtifactNode) => void;
}) {
  const [expanded, setExpanded] = useState(depth === 0);

  if (node.type === "dir") {
    return (
      <li>
        <button
          className={`tree-row dir ${expanded ? "open" : ""}`}
          style={{ paddingLeft: `${depth * 13 + 8}px` }}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="caret">{expanded ? "▾" : "▸"}</span> {node.name}
        </button>
        {expanded && (
          <ul className="tree-children">
            {(node.children ?? []).map((c) => (
              <TreeRow key={c.path ?? c.name} node={c} depth={depth + 1} onOpen={onOpen} />
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

  return (
    <div className="panel">
      <h2>Vault explorer</h2>
      <ul className="tree">
        {root && root.children ? (
          root.children.map((c) => <TreeRow key={c.path ?? c.name} node={c} depth={0} onOpen={open} />)
        ) : (
          <li className="empty">loading vault…</li>
        )}
      </ul>
      <ArtifactViewer loaded={loaded} busy={busy} onClose={() => setLoaded(null)} />
    </div>
  );
}
