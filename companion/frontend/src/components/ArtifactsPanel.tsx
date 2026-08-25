import { useCallback, useState } from "react";
import { api } from "../api";
import type { ArtifactGroup } from "../types";
import { usePolling } from "../hooks/usePolling";
import { EmptyState } from "./ui";
import { ArtifactViewer, useArtifactOpener } from "./Explorer";

type SortKey = "recent" | "name";

export function ArtifactsPanel() {
  const [groups, setGroups] = useState<ArtifactGroup[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const { loaded, setLoaded, busy, open } = useArtifactOpener();

  const refresh = useCallback(async () => {
    try {
      const data = await api.artifacts();
      setGroups(data.groups);
    } catch {
      /* ignore */
    }
  }, []);

  usePolling(refresh, 15000);

  return (
    <div className="panel">
      <div className="composer-row" style={{ marginTop: 0 }}>
        <h2>Artifacts</h2>
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          title="sort order"
          style={{ marginLeft: "auto" }}
        >
          <option value="recent">recently generated</option>
          <option value="name">name A→Z</option>
        </select>
      </div>
      {groups.map((g) =>
        g.total === 0 ? null : (
          <div key={g.id} className="artifact-group">
            <p className="artifact-label">
              {g.label} <span className="badge">{g.total}</span>
            </p>
            <ul className="artifact-list">
              {[...g.files]
                .sort((a, b) =>
                  sortKey === "recent"
                    ? (b.mtime ?? 0) - (a.mtime ?? 0)
                    : a.name.localeCompare(b.name),
                )
                .slice(0, 8)
                .map((f) => (
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
        <EmptyState hint="No artifacts yet. Approved surveys and digests land here as files in your vault." />
      )}
      <ArtifactViewer loaded={loaded} busy={busy} onClose={() => setLoaded(null)} />
    </div>
  );
}
