import { useState } from "react";
import type { AppState } from "../types";
import { api } from "../api";

export function StatusBar({ state }: { state: AppState }) {
  const stats = state.hive_stats as { papers?: number; notes?: number; concepts?: number } | undefined;
  const approvals = state.approvals_pending ?? 0;
  const suggestions = state.suggestions_open ?? 0;
  const failures = state.ingest_failures ?? 0;
  const [scanning, setScanning] = useState(false);

  const runScan = async () => {
    setScanning(true);
    try {
      await api.runProactive();
    } finally {
      setTimeout(() => setScanning(false), 800);
    }
  };

  const lastScan = state.proactive?.at
    ? new Date(state.proactive.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "never";
  return (
    <div className="status-bar">
      <span className={state.hive_ok ? "dot ok" : "dot bad"} title={`hive at ${state.hive_url}`}>
        hive {state.hive_ok ? "online" : "offline"}
      </span>
      <span className={state.llm_available ? "dot ok" : "dot warn"} title="planner LLM">
        llm {state.llm_available ? state.llm_model : "heuristic fallback"}
      </span>
      <span className="stat">papers {stats?.papers ?? "?"}</span>
      <span className="stat">notes {stats?.notes ?? "?"}</span>
      {(approvals > 0 || suggestions > 0 || failures > 0) && (
        <>
          {approvals > 0 && (
            <a className="stat badge-attention" href="#approvals" title={`${approvals} step(s) waiting for your approval`}>
              ⏸ {approvals} approval{approvals > 1 ? "s" : ""}
            </a>
          )}
          {suggestions > 0 && (
            <a className="stat badge-attention" href="#suggestions" title={`${suggestions} open suggestion(s) — check the Insights rail`}>
              💡 {suggestions} suggestion{suggestions > 1 ? "s" : ""}
            </a>
          )}
          {failures > 0 && (
            <a className="stat badge-fail" href="#discover" title={`${failures} ingestion(s) failed — see Discover for rerun`}>
              ✖ {failures} failed ingest{failures > 1 ? "ions" : ""}
            </a>
          )}
        </>
      )}
      <span className="stat" title="episodic memory records">
        episodes {state.episodes.count}
      </span>
      <span
        className="stat"
        title="learned acceptance weights per suggestion kind"
      >
        policy {Object.keys(state.policy.weights).length} signals
      </span>
      <button
        className="ghost"
        title={`Run a proactive signal scan now (last: ${lastScan})`}
        disabled={scanning}
        onClick={() => void runScan()}
      >
        {scanning ? "scanning…" : "scan now"}
      </button>
    </div>
  );
}
