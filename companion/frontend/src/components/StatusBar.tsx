import type { AppState } from "../types";
import { api } from "../api";

export function StatusBar({ state }: { state: AppState }) {
  const stats = state.hive_stats as { papers?: number; notes?: number; concepts?: number } | undefined;
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
        title="Run a proactive signal scan now"
        onClick={() => void api.runProactive()}
      >
        scan now
      </button>
    </div>
  );
}
