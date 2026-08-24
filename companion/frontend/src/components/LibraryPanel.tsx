import { useCallback, useState } from "react";
import { api } from "../api";
import type { LibraryHit } from "../types";
import { useArtifactOpener, ArtifactViewer } from "./Explorer";

export function LibraryPanel() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<LibraryHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const { loaded, setLoaded, busy: viewBusy, open } = useArtifactOpener();

  const runSearch = useCallback(async () => {
    if (query.trim().length < 2) return;
    setBusy(true);
    try {
      const data = await api.librarySearch(query.trim());
      setHits(data.items);
    } catch {
      setHits([]);
    } finally {
      setBusy(false);
    }
  }, [query]);

  return (
    <div className="discover">
      <div className="composer-row" style={{ marginTop: 0 }}>
        <input
          className="search"
          style={{ flex: 1 }}
          placeholder="search your library — titles, abstracts, concepts…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void runSearch();
          }}
        />
        <button onClick={() => void runSearch()} disabled={busy}>
          search
        </button>
      </div>
      {hits && (
        <p className="hint">
          {hits.length} matches · click one with notes to open them
        </p>
      )}
      <ul className="pool-list">
        {hits === null && (
          <li className="empty">Search across ingested papers. Results link straight to their vault notes.</li>
        )}
        {hits?.length === 0 && <li className="empty">No matches in your library.</li>}
        {hits?.map((h) => (
          <li key={h.arxiv_id} className="pool-card">
            <div className="pool-head">
              <strong>{h.title}</strong>
              {h.note_path ? (
                <button onClick={() => void open({ name: h.note_path!.split("/").pop() ?? "", type: "file", path: h.note_path!, view: "text" })}>
                  open notes
                </button>
              ) : (
                <span className="pill">no notes</span>
              )}
            </div>
            <p className="pool-meta">{h.authors} · {String(h.published).slice(0, 10)} · {h.arxiv_id}</p>
            <p className="pool-abstract">{h.abstract}</p>
          </li>
        ))}
      </ul>
      <ArtifactViewer loaded={loaded} busy={viewBusy} onClose={() => setLoaded(null)} />
    </div>
  );
}
