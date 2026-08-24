import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Episode } from "../types";

const KIND_CLASS: Record<string, string> = {
  goal: "k-goal",
  plan: "k-plan",
  step: "k-step",
  conversation: "k-conv",
  feedback: "k-feedback",
  observation: "k-obs",
};

export function EpisodeBrowser() {
  const [items, setItems] = useState<Episode[]>([]);
  const [query, setQuery] = useState("");

  const refresh = useCallback(async (q: string) => {
    try {
      const data = await api.episodes(q, 60);
      setItems([...data.items].reverse());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh("");
    const t = setInterval(() => refresh(query), 10000);
    return () => clearInterval(t);
  }, [refresh, query]);

  return (
    <div className="panel">
      <h2>Episodic memory</h2>
      <input
        className="search"
        placeholder="search episodes…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void refresh(query);
        }}
      />
      <ul className="episodes">
        {items.length === 0 && <p className="empty">No episodes yet.</p>}
        {items.map((e) => (
          <li key={e.id} className={`episode ${KIND_CLASS[e.kind] ?? ""}`}>
            <span className="ts">{e.ts.slice(5, 16).replace("T", " ")}</span>
            <span className="kind">{e.kind}</span>
            <span className="sum" title={e.summary}>
              {e.summary}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
