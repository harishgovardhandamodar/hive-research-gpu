import type { AppState } from "../types";
import { StatusBar } from "./StatusBar";

export function HeaderBar({
  state,
  theme,
  onToggleTheme,
  onOpenKG,
}: {
  state: AppState | null;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onOpenKG: () => void;
}) {
  return (
    <header className="header">
      <h1 className="brand">
        <img src="/fox-logo.png" alt="Fox Companion logo" className="brand-logo" />
        <span>
          Fox Companion
          <span className="brand-sub">for hive research</span>
        </span>
      </h1>
      {state && <StatusBar state={state} />}
      <p className="tagline">agentic research workflow — episodic memory · proactive suggestions · reinforcement learning</p>
      <div className="header-actions">
        <button className="kg-open" onClick={onOpenKG} title="Explore the knowledge graph" aria-label="Open knowledge graph">
          ⬡ Knowledge Graph
        </button>
        <button className="theme-toggle" onClick={onToggleTheme} title="Switch color theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </header>
  );
}

