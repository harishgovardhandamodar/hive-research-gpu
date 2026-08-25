import { useCallback, useState } from "react";
import { api } from "../api";
import type { CompareEdge, LibraryHit } from "../types";
import { useArtifactOpener, ArtifactViewer } from "./Explorer";

export function LibraryPanel() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<LibraryHit[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [compare, setCompare] = useState<{ edges: CompareEdge[]; ids: string[] } | null>(null);
  const [comparing, setComparing] = useState(false);
  const { loaded, setLoaded, busy: viewBusy, open } = useArtifactOpener();

  const toggleSelect = (id: string) =>
    setSelected((sel) =>
      sel.includes(id) ? sel.filter((x) => x !== id) : sel.length >= 4 ? sel : [...sel, id],
    );

  const runCompare = async () => {
    if (selected.length < 2) return;
    setComparing(true);
    try {
      const edges = await api.similarity(selected);
      setCompare({ edges, ids: [...selected] });
    } finally {
      setComparing(false);
    }
  };

  const copyCite = async (h: LibraryHit) => {
    const { bibtex } = await api.cite(h.arxiv_id, h.title, h.authors, h.published);
    try {
      await navigator.clipboard.writeText(bibtex);
      setCopied(h.arxiv_id);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  const runSearch = useCallback(async () => {
    if (query.trim().length < 2) return;
    setBusy(true);
    try {
      const data = await api.librarySearch(query.trim());
      setHits(data.items);
      setLoadError(null);
    } catch (e) {
      setHits([]);
      setLoadError(e instanceof Error ? e.message : "library search failed");
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
        <button onClick={() => void runCompare()} disabled={selected.length < 2 || comparing} title="compare up to 4 selected papers">
          {comparing ? "…" : `compare (${selected.length})`}
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
        {hits?.length === 0 && !loadError && <li className="empty">No matches in your library.</li>}
        {loadError && (
          <li className="empty" style={{ color: "var(--bad)" }}>
            {loadError}
          </li>
        )}
        {hits?.map((h) => (
          <li key={h.arxiv_id} className={`pool-card ${selected.includes(h.arxiv_id) ? "selected" : ""}`}>
            <div className="pool-head">
              <label className="pick">
                <input
                  type="checkbox"
                  checked={selected.includes(h.arxiv_id)}
                  onChange={() => toggleSelect(h.arxiv_id)}
                />
                <strong>{h.title}</strong>
              </label>
              <span style={{ display: "flex", gap: 6 }}>
                <button className="ghost" title="copy BibTeX" onClick={() => void copyCite(h)}>
                  {copied === h.arxiv_id ? "copied!" : "⎘ cite"}
                </button>
                {h.note_path ? (
                  <button onClick={() => void open({ name: h.note_path!.split("/").pop() ?? "", type: "file", path: h.note_path!, view: "text" })}>
                    open notes
                  </button>
                ) : (
                  <span className="pill">no notes</span>
                )}
              </span>
            </div>
            <p className="pool-meta">{h.authors} · {String(h.published).slice(0, 10)} · {h.arxiv_id}</p>
            <p className="pool-abstract">{h.abstract}</p>
          </li>
        ))}
      </ul>
      <ArtifactViewer loaded={loaded} busy={viewBusy} onClose={() => setLoaded(null)} />
      {compare && (
        <div className="artifact-modal" onClick={() => setCompare(null)}>
          <div className="artifact-box" onClick={(e) => e.stopPropagation()}>
            <div className="artifact-head">
              <code>comparison · {compare.ids.length} papers</code>
              <button onClick={() => setCompare(null)}>close</button>
            </div>
            <div className="artifact-scroll artifact-body">
              {compare.edges.length === 0 && (
                <p>No measurable overlap between the selected papers.</p>
              )}
              {compare.edges.length > 0 && (
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>pair</th>
                      <th>score</th>
                      <th>author overlap</th>
                      <th>abstract sim</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...compare.edges]
                      .sort((a, b) => b.score - a.score)
                      .map((e) => (
                        <tr key={`${e.source}-${e.target}`}>
                          <td>
                            {e.source_title.slice(0, 34)} ↔ {e.target_title.slice(0, 34)}
                          </td>
                          <td className="score">{e.score.toFixed(3)}</td>
                          <td>{Math.round(e.author_overlap * 100)}%</td>
                          <td>{Math.round(e.abstract_sim * 100)}%</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
