import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { TimelineResponse, TimelineThread } from "../types";

const STEP_ICON: Record<string, string> = { done: "✓", failed: "✗", skipped: "⤼" };
const STATUS_CLASS: Record<string, string> = {
  done: "tl-done",
  failed: "tl-failed",
  running: "tl-running",
  unknown: "",
};

function fmtSpan(s: number): string {
  if (!s) return "instant";
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export function TimelineView() {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    try {
      setData(await api.timeline());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, [refresh]);

  const threads = useMemo(() => {
    if (!data) return [] as TimelineThread[];
    if (!query.trim()) return data.threads;
    const q = query.toLowerCase();
    return data.threads.filter(
      (t) =>
        t.goal.toLowerCase().includes(q) ||
        t.steps.some((s) => s.summary.toLowerCase().includes(q)) ||
        t.decisions.some((d) => d.summary.toLowerCase().includes(q)),
    );
  }, [data, query]);

  return (
    <div className="panel">
      <h2>
        Agent timeline{" "}
        {data && <span className="badge">{data.total_threads}</span>}
      </h2>
      <input
        className="search"
        placeholder="filter threads…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="timeline">
        {!data && <p className="empty">loading…</p>}
        {data && threads.length === 0 && <p className="empty">No matching workflow threads.</p>}
        {threads.map((t) => (
          <div key={t.goal_id} className={`thread ${STATUS_CLASS[t.status] ?? ""}`}>
            <div className="thread-head">
              <span className={`dot tl-dot ${STATUS_CLASS[t.status] ?? ""}`} title={t.status} />
              <span className="thread-goal" title={t.goal}>
                {t.goal}
              </span>
              <span className="pill">{t.status}</span>
              <span className="stat" title={`${t.steps_ok} ok · ${t.steps_failed} failed · ${t.steps_skipped} skipped`}>
                {t.steps_ok}/{t.steps.length}
              </span>
              <span className="stat">{fmtSpan(t.span_s)}</span>
            </div>
            <ol className="rail">
              {t.decisions.map((d) => (
                <li key={"d" + d.ts} className="node node-decision">
                  <span className="node-icon">◆</span>
                  <div>
                    <span className="node-ts">{d.ts.slice(11, 19)}</span>
                    <span className="node-text">{d.summary}</span>
                  </div>
                </li>
              ))}
              {t.steps.map((s) => (
                <li key={s.ts + s.tool} className={`node node-${s.status}`}>
                  <span className="node-icon">{STEP_ICON[s.status] ?? "·"}</span>
                  <div>
                    <span className="node-ts">{s.ts.slice(11, 19)}</span>
                    <code>{s.tool}</code>
                    <span className={`node-state st-${s.status}`}>{s.status}</span>
                    <p className="node-text" title={s.summary}>
                      {s.summary}
                    </p>
                  </div>
                </li>
              ))}
              {t.steps.length === 0 && t.decisions.length === 0 && (
                <li className="node">
                  <span className="node-icon">·</span>
                  <span className="node-text">no steps recorded</span>
                </li>
              )}
            </ol>
          </div>
        ))}
        {data && data.unfiled.length > 0 && !query && (
          <details className="unfiled">
            <summary>{data.unfiled.length} other events (conversations…)</summary>
            <ul>
              {[...data.unfiled].reverse().map((e, i) => (
                <li key={i}>
                  <span className="node-ts">{e.ts.slice(5, 16).replace("T", " ")}</span> [{e.kind}] {e.summary}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
