import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ArtifactGroup } from "../types";
import { ArtifactViewer, useArtifactOpener } from "./Explorer";

export function ArtifactsPanel() {
  const [groups, setGroups] = useState<ArtifactGroup[]>([]);
  const { loaded, setLoaded, busy, open } = useArtifactOpener();

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
                <li className="artifact-more">+{g.files.length - 8} more — see vault explorer</li>
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
      <ArtifactViewer loaded={loaded} busy={busy} onClose={() => setLoaded(null)} />
    </div>
  );
}
