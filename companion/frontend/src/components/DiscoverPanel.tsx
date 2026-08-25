import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { IngestFailure, PoolPaper } from "../types";
import { usePolling } from "../hooks/usePolling";
import { toast } from "../lib/toast";

export function DiscoverPanel() {
  const [topics, setTopics] = useState<string[]>([]);
  const [papers, setPapers] = useState<PoolPaper[]>([]);
  const [failures, setFailures] = useState<IngestFailure[]>([]);
  const [activeTopic, setActiveTopic] = useState<string>("");
  const [newTopic, setNewTopic] = useState("");
  const [importing, setImporting] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.discover();
      setTopics(data.topics);
      setPapers(data.papers);
    } catch {
      /* ignore */
    }
    try {
      const f = await api.ingestFailures();
      setFailures(f.failures);
    } catch {
      /* ignore */
    }
  }, []);

  usePolling(refresh, 30000);

  // pool papers flip to "in library" as import plans finish — refresh on ws activity
  useEffect(() => {
    const onChange = () => setTimeout(refresh, 400);
    window.addEventListener("plans-changed", onChange);
    return () => window.removeEventListener("plans-changed", onChange);
  }, [refresh]);

  const doImport = async (arxivId: string) => {
    setImporting(arxivId);
    try {
      await api.importPoolPaper(arxivId, "tiered");
      toast(`queued import of ${arxivId} — approve it in the inbox`);
      await refresh();
    } finally {
      setImporting(null);
    }
  };

  const doRetry = async (ids: string[]) => {
    setImporting(ids.join(","));
    try {
      await api.retryIngest(ids, "tiered");
      toast(`queued rerun of ${ids.length} paper${ids.length > 1 ? "s" : ""}`);
      await refresh();
    } finally {
      setImporting(null);
    }
  };

  const toggleTopic = async (topic: string, action: "add" | "remove") => {
    await api.poolTopic(action, topic);
    if (action === "remove" && activeTopic === topic) setActiveTopic("");
    await refresh();
  };

  const shown = activeTopic ? papers.filter((p) => p.topics.includes(activeTopic)) : papers;

  return (
    <div className="discover">
      <div className="disc-topics">
        <span className="artifact-label">watching:</span>
        {topics.map((t) => (
          <span
            key={String(t)}
            className={`chip ${activeTopic === t ? "chip-active" : ""}`}
            onClick={() => setActiveTopic(activeTopic === String(t) ? "" : String(t))}
            title="click to filter"
          >
            {String(t)}
            <button className="chip-x" onClick={(e) => { e.stopPropagation(); void toggleTopic(String(t), "remove"); }}>×</button>
          </span>
        ))}
        <input
          className="search topic-input"
          placeholder="+ add topic"
          value={newTopic}
          onChange={(e) => setNewTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newTopic.trim().length >= 2) {
              void toggleTopic(newTopic.trim(), "add");
              setNewTopic("");
            }
          }}
        />
      </div>
      <p className="hint">{shown.length} observed preprints{activeTopic ? ` in “${activeTopic}”` : " across all topics"} · importing runs under tiered autonomy (approval gated)</p>
      {failures.length > 0 && (
        <div className="ingest-failures">
          <div className="fail-head">
            <span className="pill fail">{failures.length} failed ingestion{failures.length > 1 ? "s" : ""}</span>
            <button
              disabled={importing !== null}
              onClick={() => void doRetry(failures.map((f) => f.arxiv_id))}
            >
              {importing === failures.map((f) => f.arxiv_id).join(",") ? "queueing…" : "retry all"}
            </button>
          </div>
          <ul className="fail-list">
            {failures.map((f) => (
              <li key={f.arxiv_id} className="fail-row" title={f.error}>
                <code>{f.arxiv_id}</code>
                <span className="fail-title">{f.title || "untitled"}</span>
                <span className="fail-err">{f.error?.slice(0, 90)}{f.error && f.error.length > 90 ? "…" : ""}</span>
                <span className="fail-attempts">×{f.attempts}</span>
                <button disabled={importing !== null} onClick={() => void doRetry([f.arxiv_id])}>
                  rerun
                </button>
                <button
                  className="chip-x"
                  title="dismiss — don't suggest again"
                  onClick={() => void api.dismissIngestFailure(f.arxiv_id).then(refresh)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="pool-list">
        {shown.length === 0 && <li className="empty">Watch pool is empty here. Add a topic above and let the pool observe arxiv.</li>}
        {shown.map((p) => (
          <li key={p.arxiv_id} className={`pool-card ${p.imported ? "imported" : ""}`}>
            <div className="pool-head">
              <strong>{p.title}</strong>
              {p.imported ? (
                <span className="pill kind">in library</span>
              ) : (
                <button disabled={importing === p.arxiv_id} onClick={() => void doImport(p.arxiv_id)}>
                  {importing === p.arxiv_id ? "queueing…" : "import"}
                </button>
              )}
            </div>
            <p className="pool-meta">{p.authors} · {p.published.slice(0, 10)}</p>
            <p className="pool-abstract">{p.abstract}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
