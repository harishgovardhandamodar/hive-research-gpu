import { useCallback, useEffect, useRef, useState } from "react";
import { api, connectWs } from "./api";
import type { AppState, AutonomyMode, Plan } from "./types";
import { StatusBar } from "./components/StatusBar";
import { GoalComposer } from "./components/GoalComposer";
import { PlanCard } from "./components/PlanCard";
import { ChatPanel } from "./components/ChatPanel";
import { ApprovalInbox } from "./components/ApprovalInbox";
import { SuggestionsFeed } from "./components/SuggestionsFeed";
import { TimelineView } from "./components/TimelineView";
import { ArtifactsPanel } from "./components/ArtifactsPanel";

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const plansRef = useRef<Map<string, Plan>>(new Map());

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
        return;
      }
      const plan = plansRef.current.get(planId);
      if (!plan && event.type !== "plan_started") return;
      if (event.type === "plan_started") {
        void refreshPlans();
        return;
      }
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

  return (
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
      </header>
      {error && <div className="banner error">{error}</div>}
      <main className="columns">
        <section className="col col-goals">
          <h2>Goals &amp; Plans</h2>
          <GoalComposer onCreate={createGoal} modes={state?.autonomy_modes ?? ["approve", "tiered", "auto"]} />
          <div className="plan-list">
            {plans.length === 0 && <p className="empty">No goals yet. Describe what you need — the companion will plan and execute it.</p>}
            {[...plans].reverse().map((p) => (
              <PlanCard key={p.id} plan={p} onModeSwitch={refreshState} />
            ))}
          </div>
        </section>
        <section className="col col-chat">
          <ChatPanel />
        </section>
        <section className="col col-side">
          <ApprovalInbox onChanged={refreshPlans} />
          <SuggestionsFeed />
          <ArtifactsPanel />
          <TimelineView />
        </section>
      </main>
    </div>
  );
}
