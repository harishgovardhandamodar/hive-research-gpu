import { useCallback, useMemo, useState } from "react";
import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { EmptyState } from "./ui";
import { toast } from "../lib/toast";

interface ScientistExcerpt {
  title: string;
  url: string;
  arxiv_id: string;
  year: string;
  month: string;
  section: string;
  review_url: string;
  reviewed: boolean;
}

interface AgentTool {
  name: string;
  description: string;
  url: string;
  kind: string;
}

interface ScientistPayload {
  excerpts?: ScientistExcerpt[];
  agents?: AgentTool[];
  sections?: string[];
  source?: string;
  warning?: string;
}

export function ScientistPanel() {
  const [payload, setPayload] = useState<ScientistPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("all");
  const [view, setView] = useState<"excerpts" | "agents">("excerpts");
  const [syncing, setSyncing] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPayload(await api.scientistExcerpts());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load Awesome-AI-Scientist data");
    }
  }, []);

  usePolling(load, 60000);

  const sync = async () => {
    setSyncing(true);
    try {
      setPayload(await api.scientistRefresh());
    } finally {
      setSyncing(false);
    }
  };

  const importPaper = async (arxivId: string) => {
    setImporting(arxivId);
    try {
      await api.scientistImport(arxivId, "tiered");
      toast(`queued import of ${arxivId} — approve in the inbox`);
    } finally {
      setImporting(null);
    }
  };

  return (
    <div className="discover">
      <div className="composer-row" style={{ marginTop: 0 }}>
        <button onClick={() => void sync()} disabled={syncing} className={syncing ? "btn-busy" : ""}>
          {syncing ? (<><span className="spinner" aria-hidden /> syncing…</>) : "⟳ sync fork"}
        </button>
        <input
          className="search"
          style={{ flex: 1 }}
          placeholder="filter excerpts & agents…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="filter AI-scientist content"
        />
        <select value={view} onChange={(e) => setView(e.target.value as "excerpts" | "agents")} aria-label="content view">
          <option value="excerpts">excerpts</option>
          <option value="agents">agents & tools</option>
        </select>
        {view === "excerpts" && (
          <select value={section} onChange={(e) => setSection(e.target.value)} aria-label="section filter">
            <option value="all">all sections</option>
            {(payload?.sections ?? []).map((sec) => (
              <option key={sec} value={sec}>{sec}</option>
            ))}
          </select>
        )}
      </div>
      {error && (
        <div className="banner error" role="alert">
          <span>{error}</span>
          <button className="ghost" onClick={() => void load()}>retry</button>
        </div>
      )}
      {payload?.warning && <p className="hint" style={{ color: "var(--warn)" }}>{payload.warning}</p>}

      {view === "excerpts" && <ExcerptList payload={payload} query={query} section={section} importing={importing} onImport={(id) => void importPaper(id)} />}
      {view === "agents" && <AgentList payload={payload} query={query} />}
    </div>
  );
}

function ExcerptList({
  payload,
  query,
  section,
  importing,
  onImport,
}: {
  payload: ScientistPayload | null;
  query: string;
  section: string;
  importing: string | null;
  onImport: (arxivId: string) => void;
}) {
  const excerpts = useMemo(() => {
    let list = payload?.excerpts ?? [];
    if (section !== "all") list = list.filter((e) => e.section === section);
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((e) => `${e.title} ${e.section}`.toLowerCase().includes(q));
    return list;
  }, [payload, query, section]);

  usePolling(() => undefined, 60_000); // keep hook parity; data loads via load()

  if (!payload) return <EmptyState skeleton />;
  if (excerpts.length === 0) return <EmptyState hint="No excerpts match. Sync the fork or relax the filter." />;

  return (
    <>
      <p className="hint">{excerpts.length} curated excerpts · source: Awesome-AI-Scientist</p>
      <ul className="pool-list">
        {excerpts.map((e, i) => (
          <li key={`${e.arxiv_id}-${i}`} className="pool-card">
            <div className="pool-head">
              <strong>{e.title}</strong>
              {e.year && <span className="pill kind">{e.year}.{e.month}</span>}
            </div>
            <p className="pool-meta">{e.section}</p>
            <div className="composer-row">
              {e.url && <a className="ghost" href={e.url} target="_blank" rel="noreferrer">paper ↗</a>}
              {e.review_url && <a className="ghost" href={e.review_url} target="_blank" rel="noreferrer">review ↗</a>}
              {e.review_url?.includes("ai-researcher.net") && <span className="pill kind">AI review</span>}
              {!e.reviewed && !e.review_url && <span className="stat">no review</span>}
              {e.arxiv_id && (
                <button disabled={importing === e.arxiv_id} onClick={() => onImport(e.arxiv_id)}>
                  {importing === e.arxiv_id ? "queueing…" : "ingest"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function AgentList({ payload, query }: { payload: ScientistPayload | null; query: string }) {
  const agents = useMemo(() => {
    let list = payload?.agents ?? [];
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((a) => `${a.name} ${a.description}`.toLowerCase().includes(q));
    return list;
  }, [payload, query]);

  if (!payload) return <EmptyState skeleton />;
  if (agents.length === 0) return <EmptyState hint="No agent/tool projects match." />;

  return (
    <>
      <p className="hint">{agents.length} research-automation projects from the featured list</p>
      <ul className="pool-list">
        {agents.map((a, i) => (
          <li key={`${a.name}-${i}`} className={`pool-card ${a.kind === "platform" ? "platform" : ""}`}>
            <div className="pool-head">
              <strong>{a.name}</strong>
              <span className="pill kind">{a.kind}</span>
            </div>
            <p className="pool-meta">{a.description}</p>
            {a.url && (
              <div className="composer-row">
                <a className="ghost" href={a.url} target="_blank" rel="noreferrer">open ↗</a>
              </div>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
