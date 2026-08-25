import { useCallback, useEffect, useRef, useState } from "react";
import { api, connectWs } from "../api";
import type { Plan } from "../types";

/**
 * Owns the live plan state: WS connection, event folding into plan steps,
 * and the `plans-changed` window event other panels listen for.
 */
export function useLivePlans() {
  const [plans, setPlans] = useState<Plan[]>([]);
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
        if (event.type === "suggestion" || event.type === "suggestion_resolved")
          window.dispatchEvent(new Event("suggestions-changed"));
        if (event.type === "ingest_failed" || event.type === "idea")
          window.dispatchEvent(new Event("hive-activity"));
        return;
      }
      const plan = plansRef.current.get(planId);
      if (!plan && event.type !== "plan_started") return;
      if (event.type === "plan_started") {
        void refreshPlans();
        return;
      }
      if (!plan) return;
      // let live panels (Discover etc.) react to plan activity without polling
      window.dispatchEvent(new Event("plans-changed"));

      const stepIdx = event.step_index as number | undefined;
      const step = stepIdx !== undefined ? plan.steps[stepIdx] : undefined;
      if (event.type === "awaiting_approval" && step) step.state = "awaiting_approval";
      else if (event.type === "step_started" && step) step.state = "running";
      else if (event.type === "step_finished" && step) step.state = event.ok ? "done" : "failed";
      else if (event.type === "plan_finished") plan.status = String(event.status ?? "done");
      setPlans([...plansRef.current.values()]);
    },
    [refreshPlans],
  );

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const open = () => {
      ws = connectWs(applyEvent);
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

  return { plans, plansRef, refreshPlans };
}
