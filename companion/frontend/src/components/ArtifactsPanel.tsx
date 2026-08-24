import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ArtifactGroup } from "../types";

interface Loaded {
  path: string;
  content: string;
}

export function ArtifactsPanel() {
  const [groups, setGroups] = useState<ArtifactGroup[]>([]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.artifacts();
      setGroups(data.groups);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  const open = async (path: string) => {
    setBusy(true);
    try {
      const data = await api.artifactContent(path);
      setLoaded({ path, content: data.content });
    } catch (err) {
      setLoaded({ path, content: `Could not load artifact: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>Artifacts</h2>
      {groups.map((g) =>
        g.total === 0 ? null : (
          <div key={g.id} className="artifact-group">
            <p className="artifact-label">
              {g.label} <span className="badge">{g.total}</span>
            </p>
            <ul className="artifact-list">
              {g.files.slice(0, 8).map((f) => (
                <li key={f.path}>
                  <button className="artifact-file" onClick={() => void open(f.path)} title={f.path}>
                    {f.name}
                  </button>
                </li>
              ))}
              {g.files.length > 8 && (
                <li className="artifact-more">+{g.files.length - 8} more</li>
              )}
            </ul>
          </div>
        ),
      )}
      {groups.every((g) => g.total === 0) && (
        <p className="empty">
          No artifacts yet. Approved surveys and digests land here as files in your vault.
        </p>
      )}
      {busy && <p className="typing">loading artifact…</p>}
      {loaded && (
        <div className="artifact-modal" onClick={() => setLoaded(null)}>
          <div className="artifact-box" onClick={(e) => e.stopPropagation()}>
            <div className="artifact-head">
              <code>{loaded.path}</code>
              <button onClick={() => setLoaded(null)}>close</button>
            </div>
            <pre className="artifact-body">{loaded.content}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
