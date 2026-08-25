import { memo, useCallback, useEffect, useRef, useState } from "react";
import { api, connectWs } from "./api";
import type { AppState, AutonomyMode, Plan } from "./types";
import { PulseProvider, usePulse } from "./hooks/usePulse";
import { useLayout } from "./hooks/useLayout";
import { StatusBar } from "./components/StatusBar";
import { GoalComposer } from "./components/GoalComposer";
import { PlanCard } from "./components/PlanCard";
import { ChatPanel } from "./components/ChatPanel";
import { ApprovalInbox } from "./components/ApprovalInbox";
import { SuggestionsFeed } from "./components/SuggestionsFeed";
import { TimelineView } from "./components/TimelineView";
import { ArtifactsPanel } from "./components/ArtifactsPanel";
import { Explorer } from "./components/Explorer";
import { JobsBar } from "./components/JobsBar";
import { KnowledgeGraph } from "./components/KnowledgeGraph";
import { DiscoverPanel } from "./components/DiscoverPanel";
import { LibraryPanel } from "./components/LibraryPanel";
import { SchedulesPanel } from "./components/SchedulesPanel";
import { IdeasPanel } from "./components/IdeasPanel";
import { DeepIdeasPanel } from "./components/DeepIdeasPanel";
import { AgentsPanel } from "./components/AgentsPanel";
import { Toaster } from "./lib/toast";

const MemoPlanCard = memo(PlanCard);
const MemoApprovalInbox = memo(ApprovalInbox);

type CenterTab = "chat" | "agents" | "discover" | "ideas" | "deepideas" | "library";

/** Workspace tabs — add an entry here to extend the center column. */
const TABS: { id: CenterTab; label: string }[] = [
  { id: "chat", label: "Fox Chat" },
  { id: "agents", label: "🤖 Agents" },
  { id: "discover", label: "Discover" },
  { id: "ideas", label: "💡 IDEAgent" },
  { id: "deepideas", label: "🕸 Deep Ideation" },
  { id: "library", label: "Library" },
];

const TAB_COMPONENTS: Record<CenterTab, () => JSX.Element> = {
  chat: ChatPanel,
  agents: AgentsPanel,
  discover: DiscoverPanel,
  ideas: IdeasPanel,
  deepideas: DeepIdeasPanel,
  library: LibraryPanel,
};

function GlobalProgress() {
  const { snap } = usePulse();
  if (snap.plan_progress.length === 0) return null;
  const avg = snap.plan_progress.reduce((a, p) => a + p.progress, 0) / snap.plan_progress.length;
  const pct = Math.round(avg * 100);
  return (
    <div className="global-progress" aria-label={`${snap.plan_progress.length} agentic tasks running, ${pct}% avg`}>
      <div className="global-progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

function Gutter({
  id,
  onDrag,
  onNudge,
}: {
  id: string;
  onDrag: (ev: React.MouseEvent) => void;
  onNudge: (dir: number) => void;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${id} panels`}
      tabIndex={0}
      className="gutter"
      onMouseDown={onDrag}
      onDoubleClick={() => onNudge(0)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onNudge(-1);
        if (e.key === "ArrowRight") onNudge(1);
      }}
    />
  );
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showKG, setShowKG] = useState(false);
  const [centerTab, setCenterTab] = useState<CenterTab>("chat");
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    (localStorage.getItem("fox-theme") as "light" | null) === "light" ? "light" : "dark",
  );
  const plansRef = useRef<Map<string, Plan>>(new Map());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("fox-theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const layout = useLayout();

  useEffect(() => {
    // any failed API call anywhere surfaces in the banner
    const onApiError = (ev: Event) => {
      const detail = (ev as CustomEvent<{ message: string }>).detail;
      if (detail?.message) setError(detail.message);
    };
    window.addEventListener("api-error", onApiError);
    return () => window.removeEventListener("api-error", onApiError);
  }, []);

  const refreshPlans = useCallback(async () => {
    try {
      const list = await api.plans();
      plansRef.current = new Map(list.map((p) => [p.id, p]));
      setPlans(list);
    } catch {
      /* server restarting */
    }
  }, []);

  const refreshState = useCallback(async () => {
    try {
      setState(await api.state());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refreshState();
    refreshPlans();
    const t = setInterval(refreshState, 15000);
    return () => clearInterval(t);
  }, [refreshState, refreshPlans]);

  const applyEvent = useCallback(
    (raw: MessageEvent) => {
      let event: Record<string, unknown>;
      try {
        event = JSON.parse(raw.data as string);
      } catch {
        return;
      }
      const planId = event.plan_id as string | undefined;
      if (!planId) {
        if (event.type === "suggestion" || event.type === "suggestion_resolved") window.dispatchEvent(new Event("suggestions-changed"));
        if (event.type === "ingest_failed" || event.type === "idea") window.dispatchEvent(new Event("hive-activity"));
        return;
      }
      const plan = plansRef.current.get(planId);
      if (!plan && event.type !== "plan_started") return;
      if (event.type === "plan_started") {
        void refreshPlans();
        return;
      }
      // let live panels (Discover etc.) react to plan activity without polling
      window.dispatchEvent(new Event("plans-changed"));
      if (event.type === "awaiting_approval" && plan) {
        const step = plan.steps[event.step_index as number];
        if (step) step.state = "awaiting_approval";
        setPlans([...plansRef.current.values()]);
        return;
      }
      if (!plan) return;
      if (event.type === "step_started") {
        const step = plan.steps[event.step_index as number];
        if (step) step.state = "running";
      } else if (event.type === "step_finished") {
        const step = plan.steps[event.step_index as number];
        if (step) step.state = event.ok ? "done" : "failed";
      } else if (event.type === "plan_finished") {
        plan.status = String(event.status ?? "done");
      }
      setPlans([...plansRef.current.values()]);
    },
    [refreshPlans],
  );

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const open = () => {
      ws = connectWs(applyEvent);
      ws.onopen = () => setError(null);
      ws.onclose = () => {
        retry = setTimeout(open, 3000);
      };
    };
    open();
    return () => {
      clearTimeout(retry);
      ws?.close();
    };
  }, [applyEvent]);

  const createGoal = async (goal: string, mode: AutonomyMode) => {
    await api.createGoal(goal, mode);
    await refreshPlans();
  };

  const { state: ly, containerRef, beginDrag, nudge, toggleLeft, toggleRight, resetLayout } = layout;

  return (
    <PulseProvider>
      <div className="app">
        <header className="header">
          <h1 className="brand">
            <img src="/fox-logo.png" alt="Fox Companion logo" className="brand-logo" />
            <span>
              Fox Companion
              <span className="brand-sub">for hive research</span>
            </span>
          </h1>
          <p className="tagline">agentic research workflow — episodic memory · proactive suggestions · reinforcement learning</p>
          {state && <StatusBar state={state} />}
          <button
            className="theme-toggle"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="Switch color theme"
          >
            {theme === "dark" ? "☀ light" : "☾ dark"}
          </button>
          <button className="kg-open" onClick={() => setShowKG(true)} title="Explore the knowledge graph" aria-label="Open knowledge graph">
            ⬡ Knowledge Graph
          </button>
        </header>
        <GlobalProgress />
        {error && (
          <div className="banner error" role="alert">
            <span>{error}</span>
            <button className="ghost" onClick={() => setError(null)} title="Dismiss">✕</button>
          </div>
        )}
        <main className="columns" ref={containerRef}>
          {/* ── left rail (collapsed) ── */}
          {ly.collapsedLeft && (
            <button className="collapsed-rail rail-left" onClick={toggleLeft} title="Show goals panel">
              ⫿ Goals
            </button>
          )}

          {!ly.collapsedLeft && (
            <section className="col col-goals" style={{ width: `${ly.leftPct}%` }}>
              <div className="col-head">
                <h2>Goals &amp; Plans</h2>
                <button className="col-collapse" onClick={toggleLeft} title="Collapse panel">
                  ⟨
                </button>
              </div>
              <div className="col-body">
                <GoalComposer onCreate={createGoal} modes={state?.autonomy_modes ?? ["approve", "tiered", "auto"]} />
                <div className="plan-list">
                  {plans.length === 0 && (
                    <p className="empty">No goals yet. Describe what you need — the companion will plan and execute it.</p>
                  )}
                  {[...plans].reverse().map((p) => (
                    <MemoPlanCard key={p.id} plan={p} onModeSwitch={refreshState} />
                  ))}
                </div>
                <SchedulesPanel />
                <Explorer />
              </div>
            </section>
          )}

          {!ly.collapsedLeft && <Gutter id="left" onDrag={beginDrag("left")} onNudge={(d) => nudge("left", d)} />}

          {/* ── workspace ── */}
          <section className="col col-chat" style={{ width: `${ly.centerPct}%` }}>
            <div className="col-head">
              <div className="center-tabs" role="tablist" aria-label="Workspace sections">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    role="tab"
                    aria-selected={centerTab === t.id}
                    tabIndex={centerTab === t.id ? 0 : -1}
                    className={centerTab === t.id ? "tabbtn active" : "tabbtn"}
                    onClick={() => setCenterTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {(ly.collapsedLeft || ly.collapsedRight) && (
                <button className="col-collapse" onClick={ly.collapsedLeft ? toggleLeft : toggleRight} title="Expand side panel">
                  ⟩
                </button>
              )}
            </div>
            <div className="col-body">
              {(() => {
                const Panel = TAB_COMPONENTS[centerTab];
                return <Panel />;
              })()}
            </div>
          </section>

          {!ly.collapsedRight && <Gutter id="right" onDrag={beginDrag("right")} onNudge={(d) => nudge("right", d)} />}

          {/* ── right rail (collapsed) ── */}
          {ly.collapsedRight && (
            <button className="collapsed-rail rail-right" onClick={toggleRight} title="Show insights panel">
              Insights ⫸
            </button>
          )}

          {!ly.collapsedRight && (
            <section className="col col-side" style={{ width: `${ly.rightPct}%` }}>
              <div className="col-head">
                <h2>Insights</h2>
                <button className="col-collapse" onClick={toggleRight} title="Collapse panel">
                  ⟩
                </button>
              </div>
              <div className="col-body">
                <MemoApprovalInbox onChanged={refreshPlans} />
                <SuggestionsFeed />
                <ArtifactsPanel />
                <TimelineView />
              </div>
            </section>
          )}
        </main>
        <footer className="layout-footer">
          <button className="ghost" onClick={resetLayout} title="Reset panel widths">
            reset layout
          </button>
          <span className="stat">drag gutters to resize · double-click a gutter to even out</span>
        </footer>
        {showKG && <KnowledgeGraph onClose={() => setShowKG(false)} />}
        <JobsBar />
        <Toaster />
      </div>
    </PulseProvider>
  );
}
