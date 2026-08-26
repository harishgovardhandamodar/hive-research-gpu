import { useCallback, useState } from "react";
import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { toast } from "../lib/toast";
import { EmptyState } from "./ui";
import type { ScientistAgentTool, ScientistPayload } from "../types";

export function ScientistPanel() {
  const [payload, setPayload] = useState<ScientistPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [syncing, setSyncing] = useState(false);

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
      toast("fork synced");
    } finally {
      setSyncing(false);
    }
  };

  const scientistIngestAll = async () => {
    const remaining = payload?.remaining ?? 0;
    if (remaining === 0) return;
    if (
      !window.confirm(
        `Ingest ${remaining} AI-Scientist papers into the knowledge graph? Each runs the full analysis pipeline — this will take a while.`,
      )
    )
      return;
    try {
      const res = await api.scientistIngestAll("auto");
      if (res.queued) toast(`queued bulk ingestion of ${res.remaining} papers — approve once in the inbox`);
      else toast(res.message ?? "nothing to ingest", "info");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "bulk ingest failed", "error");
    }
  };

  const agents: ScientistAgentTool[] = [...(payload?.agents ?? [])].filter((a) =>
    query.trim() === "" ? true : `${a.name} ${a.description}`.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="discover">
      <div className="composer-row" style={{ marginTop: 0 }}>
        <button onClick={() => void sync()} disabled={syncing} className={syncing ? "btn-busy" : ""}>
          {syncing ? (
            <>
              <span className="spinner" aria-hidden /> syncing…
            </>
          ) : (
            "⟳ sync fork"
          )}
        </button>
        <input
          className="search"
          style={{ flex: 1 }}
          placeholder="filter agents & tools…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="filter AI-scientist agents"
        />
        <button
          onClick={() => void scientistIngestAll()}
          disabled={(payload?.remaining ?? 0) === 0}
          title={
            payload?.remaining
              ? `ingest ${payload.remaining} excerpts into the knowledge graph (tagged orange nodes)`
              : "all excerpts already ingested"
          }
        >
          ⬇ ingest all ({payload?.remaining ?? "…"})
        </button>
      </div>
      {error && (
        <div className="banner error" role="alert">
          <span>{error}</span>
          <button className="ghost" onClick={() => void load()}>
            retry
          </button>
        </div>
      )}
      {payload?.warning && (
        <p className="hint" style={{ color: "var(--warn)" }}>
          {payload.warning}
        </p>
      )}
      {payload && (
        <p className="hint">
          corpus: {payload.total_with_arxiv ?? 0} papers tracked · {payload.remaining ?? 0} pending · ingested nodes appear{" "}
          <span style={{ color: "#fb923c" }}>orange</span> in the knowledge graph, with their excerpt on hover
        </p>
      )}

      {!payload && !error && <EmptyState skeleton />}
      {payload && agents.length === 0 && <EmptyState hint="No agent/tool projects match your filter." />}

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
                <a className="ghost" href={a.url} target="_blank" rel="noreferrer">
                  open ↗
                </a>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
