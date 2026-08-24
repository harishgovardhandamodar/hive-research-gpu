import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface PoolPaper {
  arxiv_id: string;
  title: string;
  authors: string;
  published: string;
  abstract: string;
  topics: string[];
  imported: boolean;
}

export function DiscoverPanel() {
  const [topics, setTopics] = useState<string[]>([]);
  const [papers, setPapers] = useState<PoolPaper[]>([]);
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
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  const doImport = async (arxivId: string) => {
    setImporting(arxivId);
    try {
      await api.importPoolPaper(arxivId, "tiered");
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
            key={t}
            className={`chip ${activeTopic === t ? "chip-active" : ""}`}
            onClick={() => setActiveTopic(activeTopic === t ? "" : t)}
            title="click to filter"
          >
            {t}
            <button className="chip-x" onClick={(e) => { e.stopPropagation(); void toggleTopic(t, "remove"); }}>×</button>
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
