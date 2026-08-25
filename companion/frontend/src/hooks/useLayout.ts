import { useCallback, useEffect, useRef, useState } from "react";

export interface LayoutState {
  leftPct: number;
  centerPct: number;
  rightPct: number;
  collapsedLeft: boolean;
  collapsedRight: boolean;
}

const DEFAULTS: LayoutState = {
  leftPct: 27,
  centerPct: 42,
  rightPct: 31,
  collapsedLeft: false,
  collapsedRight: false,
};

const STORAGE_KEY = "fox-layout-v1";
export const MIN_PCT = 14;
export const MAX_PCT = 58;

function clampPct(v: number) {
  return Math.max(MIN_PCT, Math.min(MAX_PCT, v));
}

/** Persisted, resizable VS Code-style column layout. */
export function useLayout() {
  const [state, setState] = useState<LayoutState>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<LayoutState>;
        return {
          leftPct: clampPct(parsed.leftPct ?? DEFAULTS.leftPct),
          centerPct: clampPct(parsed.centerPct ?? DEFAULTS.centerPct),
          rightPct: clampPct(parsed.rightPct ?? DEFAULTS.rightPct),
          collapsedLeft: !!parsed.collapsedLeft,
          collapsedRight: !!parsed.collapsedRight,
        };
      }
    } catch {
      /* fall through */
    }
    return DEFAULTS;
  });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* ignore quota errors */
    }
  }, [state]);

  /** Normalize so the three visible columns fill the row. */
  const normalize = useCallback((s: LayoutState): LayoutState => {
    if (s.collapsedLeft && s.collapsedRight) {
      return { ...s, centerPct: 100 - MIN_PCT * 2 };
    }
    if (s.collapsedLeft) {
      return { ...s, centerPct: clampPct(100 - s.rightPct) };
    }
    if (s.collapsedRight) {
      return { ...s, leftPct: clampPct(s.leftPct), centerPct: 100 - clampPct(s.leftPct) };
    }
    const total = s.leftPct + s.centerPct + s.rightPct;
    if (total === 100) return s;
    return { ...s, centerPct: clampPct(100 - s.leftPct - s.rightPct) };
  }, []);

  const setWidths = useCallback(
    (leftPct: number, centerPct: number, rightPct: number) => {
      setState((s) => normalize({ ...s, leftPct: clampPct(leftPct), centerPct: clampPct(centerPct), rightPct: clampPct(rightPct) }));
    },
    [normalize],
  );

  const beginDrag = useCallback(
    (gutter: "left" | "right") => (ev: React.MouseEvent) => {
      ev.preventDefault();
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const startX = ev.clientX;
      const start = { ...state };
      let latest = { ...start };

      const onMove = (e: MouseEvent) => {
        const deltaPct = ((e.clientX - startX) / rect.width) * 100;
        if (gutter === "left") {
          const nl = clampPct(start.leftPct + deltaPct);
          const nc = clampPct(100 - nl - start.rightPct);
          latest = { ...start, leftPct: nl, centerPct: nc, rightPct: start.rightPct };
        } else {
          const nr = clampPct(start.rightPct - deltaPct);
          const nc = clampPct(100 - start.leftPct - nr);
          latest = { ...start, rightPct: nr, centerPct: nc, leftPct: start.leftPct };
        }
        setWidths(latest.leftPct, latest.centerPct, latest.rightPct);
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [state, setWidths],
  );

  const nudge = useCallback(
    (gutter: "left" | "right", dir: number) => {
      const d = dir * 2;
      if (gutter === "left") {
        const nl = clampPct(state.leftPct + d);
        setWidths(nl, clampPct(100 - nl - state.rightPct), state.rightPct);
      } else {
        const nr = clampPct(state.rightPct + d);
        setWidths(clampPct(100 - nr - state.centerPct), state.centerPct, nr);
      }
    },
    [state, setWidths],
  );

  const toggleLeft = useCallback(
    () =>
      setState((s) => {
        const next = { ...s, collapsedLeft: !s.collapsedLeft };
        return normalize(next);
      }),
    [normalize],
  );

  const toggleRight = useCallback(
    () =>
      setState((s) => {
        const next = { ...s, collapsedRight: !s.collapsedRight };
        return normalize(next);
      }),
    [normalize],
  );

  const resetLayout = useCallback(() => setState(DEFAULTS), []);

  return {
    state,
    containerRef,
    beginDrag,
    nudge,
    toggleLeft,
    toggleRight,
    resetLayout,
  };
}
