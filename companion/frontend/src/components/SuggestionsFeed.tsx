import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { AutonomySelect, EmptyState } from "./ui";
import { toast } from "../lib/toast";
import type { AutonomyMode, Suggestion } from "../types";

export function SuggestionsFeed() {
  const [items, setItems] = useState<Suggestion[]>([]);
  const [mode, setMode] = useState<AutonomyMode>("tiered");

  const refresh = useCallback(async () => {
    try {
      setItems(await api.suggestions());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    const onChange = () => setTimeout(refresh, 500);
    window.addEventListener("suggestions-changed", onChange);
    return () => {
      clearInterval(t);
      window.removeEventListener("suggestions-changed", onChange);
    };
  }, [refresh]);

  const accept = async (id: string) => {
    await api.acceptSuggestion(id, mode);
    toast("suggestion accepted — plan launched");
    await refresh();
  };
  const reject = async (id: string) => {
    await api.rejectSuggestion(id);
    toast("suggestion dismissed", "info");
    await refresh();
  };

  return (
    <div className="panel">
      <h2>
        Proactive suggestions{" "}
        {items.length > 0 && <span className="badge">{items.length}</span>}
      </h2>
      <div className="composer-row">
        <AutonomySelect
          value={mode}
          onChange={(m) => setMode(m as AutonomyMode)}
          modes={["approve", "tiered", "auto"]}
          label="accept under"
        />
      </div>
      {items.length === 0 && (
        <EmptyState hint="No open suggestions. The companion watches your library state in the background and will speak up when something needs attention." />
      )}
      {items.map((s) => (
        <div key={s.id} className="suggestion-card">
          <div className="sugg-head">
            <span className="pill kind">{s.kind}</span>
            <span className="score" title="signal strength × learned acceptance weight">
              score {s.score.toFixed(2)}
            </span>
          </div>
          <p className="sugg-title">{s.title}</p>
          <p className="hint">{s.rationale}</p>
          <div className="composer-row">
            <button className="ok" onClick={() => void accept(s.id)}>
              do it
            </button>
            <button className="bad" onClick={() => void reject(s.id)}>
              not now
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
