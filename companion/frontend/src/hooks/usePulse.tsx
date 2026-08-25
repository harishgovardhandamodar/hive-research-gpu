import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { req } from "../api";

export interface PulseSnapshot {
  hive_ok: boolean;
  plans_running: number;
  approvals_pending: number;
  suggestions_open: number;
  fox_jobs: { id: string; status: string; stage: string; progress: number }[];
  hive_jobs: { label: string; status: string }[];
  episodes: number;
  last_scan: string | null;
  plan_progress: { id: string; goal: string; status: string; total: number; done: number; progress: number; current_tool: string; current_state: string }[];
}

const EMPTY: PulseSnapshot = {
  hive_ok: false,
  plans_running: 0,
  approvals_pending: 0,
  suggestions_open: 0,
  fox_jobs: [],
  hive_jobs: [],
  episodes: 0,
  last_scan: null,
  plan_progress: [],
};

interface PulseCtx {
  snap: PulseSnapshot;
  refreshNow: () => Promise<void>;
}

const Ctx = createContext<PulseCtx>({ snap: EMPTY, refreshNow: async () => undefined });

/**
 * Single consolidated 5s poll for all always-on indicators.
 * Replaces per-component timers for status/jobs/approval counts.
 */
export function PulseProvider({ children }: { children: React.ReactNode }) {
  const [snap, setSnap] = useState<PulseSnapshot>(EMPTY);
  const inFlight = useRef(false);

  const refreshNow = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const data = await req<PulseSnapshot & { plan_progress?: PulseSnapshot["plan_progress"] }>("/api/statusbar");
      setSnap({ ...EMPTY, ...data, plan_progress: data.plan_progress ?? [] });
    } catch {
      /* keep last known */
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void refreshNow();
    const t = setInterval(() => void refreshNow(), 5000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshNow();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refreshNow]);

  const value = useMemo(() => ({ snap, refreshNow }), [snap, refreshNow]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePulse(): PulseCtx {
  return useContext(Ctx);
}
