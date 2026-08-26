import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState } from "./ui";
import type { Episode, TimelineResponse, TimelineThread } from "../types";

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

const KIND_ICON: Record<string, string> = {
  reflection: "\u{1FA9F}",
  verdict: "\u2696\uFE0F",
  insight: "\u{1F4A1}",
  goal: "\u{1F3AF}",
  plan: "\u{1F4CB}",
  step: "\u2699\uFE0F",
  observation: "\u{1F50D}",
  feedback: "\u{1F4AC}",
  conversation: "\u{1F4AD}",
  suggestion: "\u{1F4A1}",
};

/** Decision nodes carry special agentic artifacts — give them their own glyph. */
function decisionIcon(summary: string): string {
  const lower = summary.toLowerCase();
  if (lower.startsWith("success-criteria verdict")) return summary.includes("pass") ? "\u2705" : "\u274C";
  if (lower.startsWith("success-criteria")) return KIND_ICON.verdict;
  if (lower.includes("reflection:")) return KIND_ICON.reflection;
  if (lower.includes("insight")) return KIND_ICON.insight;
  if (lower.includes("budget") || lower.includes("skipped")) return "\u23F8";
  return "\u25C6";
}

function episodeIcon(kind: string): string {
  return KIND_ICON[kind] ?? (STEP_ICON[kind] ? STEP_ICON[kind] : "\u25CF");
}

function formatContext(ctx: Record<string, unknown>): string | null {
  if (!ctx || Object.keys(ctx).length === 0) return null;
  try {
    const filtered: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(ctx)) {
      if (k === "result" && typeof v === "object" && v !== null) {
        const s = JSON.stringify(v);
        filtered[k] = s.length > 800 ? JSON.parse(s.slice(0, 800) + '}"') : v;
      } else {
        filtered[k] = v;
      }
    }
    return JSON.stringify(filtered, null, 2);
  } catch {
    return String(ctx);
  }
}

function TimelineDetailOverlay({
  goalId,
  onClose,
}: {
  goalId: string;
  onClose: () => void;
}) {
  const [episodes, setEpisodes] = useState<Episode[] | null>(null);
  const [thread, setThread] = useState<TimelineThread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.timelineThread(goalId);
        if (cancelled) return;
        setEpisodes(data.episodes);
        setThread(data.thread ?? null);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        // fallback: try episodesByGoal
        try {
          const data2 = await api.episodesByGoal(goalId, 500);
          if (cancelled) return;
          setEpisodes(data2.items);
          setError(null);
        } catch (e2) {
          if (cancelled) return;
          setError(e2 instanceof Error ? e2.message : String(e2));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [goalId]);

  const sortedEpisodes = useMemo(() => {
    if (!episodes) return [];
    return [...episodes].sort((a, b) => a.ts.localeCompare(b.ts));
  }, [episodes]);

  const stats = useMemo(() => {
    if (!sortedEpisodes.length) return null;
    const byKind: Record<string, number> = {};
    for (const e of sortedEpisodes) byKind[e.kind] = (byKind[e.kind] ?? 0) + 1;
    return byKind;
  }, [sortedEpisodes]);

  return (
    <div className="kg-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="kg-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 860, width: "96vw", maxHeight: "90vh", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div className="kg-head" style={{ flexShrink: 0 }}>
          <h2 style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 18 }}>{KIND_ICON.goal}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={thread?.goal ?? goalId}>
              {thread?.goal ?? `Goal ${goalId}`}
            </span>
            {thread && <span className="pill">{thread.status}</span>}
          </h2>
          <button onClick={onClose} aria-label="Close overlay">close</button>
        </div>

        {thread && (
          <div style={{ display: "flex", gap: 12, padding: "10px 14px", borderBottom: "1px solid var(--border, #1e293b)", flexWrap: "wrap", fontSize: 12, color: "#94a3b8", flexShrink: 0 }}>
            <span title={thread.started}>started {thread.started.slice(0, 16).replace("T", " ")}</span>
            <span>· {fmtSpan(thread.span_s)}</span>
            <span className="pill" title={`${thread.steps_ok} ok · ${thread.steps_failed} failed · ${thread.steps_skipped} skipped`}>
              {thread.steps_ok}/{thread.steps.length} steps
            </span>
            <span>· {thread.decisions.length} decisions</span>
            {stats && <span>· {sortedEpisodes.length} episodes ({Object.entries(stats).map(([k, v]) => `${k}:${v}`).join(" ")})</span>}
          </div>
        )}

        {error && (
          <div className="banner error" style={{ margin: "8px 14px", flexShrink: 0 }}>
            {error}
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          {!episodes && !error && <div className="empty">Loading episodic memory…</div>}
          {episodes && sortedEpisodes.length === 0 && <div className="empty">No episodes for this goal.</div>}
          {sortedEpisodes.map((ep, idx) => {
            const isExpanded = expanded.has(ep.id);
            const ctxStr = formatContext(ep.context);
            const stepNum = idx + 1;
            return (
              <div key={ep.id} className="thread" style={{ borderLeft: "3px solid var(--border, #334155)", paddingLeft: 10, background: "var(--surface, #0f172a)", borderRadius: 6, padding: "8px 10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span
                    className="pill"
                    style={{ fontSize: 11, minWidth: 22, textAlign: "center", background: ep.kind === "step" ? (ep.context?.status === "failed" ? "#450a0a" : ep.context?.status === "done" ? "#052e16" : "#1e293b") : "#1e293b" }}
                  >
                    {episodeIcon(ep.kind)} {ep.kind}
                  </span>
                  <span className="node-ts" style={{ fontSize: 11, color: "#64748b" }}>
                    #{stepNum} · {ep.ts.slice(0, 19).replace("T", " ")}
                  </span>
                  <span style={{ fontSize: 11, color: "#475569" }}>{ep.id.slice(0, 8)}</span>
                  {ep.context?.tool ? <code style={{ fontSize: 11, background: "#1e293b", padding: "2px 6px", borderRadius: 4 }}>{String(ep.context.tool)}</code> : null}
                  {ep.context?.status ? <span className={`pill st-${String(ep.context.status)}`} style={{ fontSize: 11 }}>{String(ep.context.status)}</span> : null}
                </div>
                <div style={{ marginTop: 6, fontSize: 13, lineHeight: 1.5, color: "#e2e8f0", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {ep.summary}
                </div>
                {ctxStr && (
                  <div style={{ marginTop: 6 }}>
                    <button
                      className="ghost"
                      style={{ fontSize: 11, padding: "2px 8px" }}
                      onClick={() => toggleExpanded(ep.id)}
                      aria-expanded={isExpanded}
                    >
                      {isExpanded ? "hide details" : "show details"}
                    </button>
                    {isExpanded && (
                      <pre style={{ marginTop: 6, background: "#020617", border: "1px solid #1e293b", borderRadius: 6, padding: 8, fontSize: 11, overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {ctxStr}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 14px", borderTop: "1px solid var(--border, #1e293b)", flexShrink: 0, fontSize: 11, color: "#64748b" }}>
          <span>Step-by-step episodic memory · {sortedEpisodes.length} events</span>
          <button className="ghost" onClick={onClose}>
            close
          </button>
        </div>
      </div>
    </div>
  );
}

export function TimelineView() {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [query, setQuery] = useState("");
  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);

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
        {!data && <EmptyState skeleton />}
        {data && threads.length === 0 && <EmptyState hint="No matching workflow threads." />}
        {threads.map((t) => (
          <div
            key={t.goal_id}
            className={`thread ${STATUS_CLASS[t.status] ?? ""}`}
            onClick={() => setSelectedGoalId(t.goal_id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setSelectedGoalId(t.goal_id);
              }
            }}
            title="Click to view detailed episodic overlay"
            style={{ cursor: "pointer" }}
          >
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
              <span className="stat" style={{ marginLeft: "auto", fontSize: 10, opacity: 0.7 }}>
                view details →
              </span>
            </div>
            <ol className="rail">
              {t.decisions.map((d) => (
                <li key={"d" + d.ts} className="node node-decision">
                  <span className="node-icon">{decisionIcon(d.summary)}</span>
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
                    <span className="node-text" title={s.summary}>
                      {s.summary}
                    </span>
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
      {selectedGoalId && <TimelineDetailOverlay goalId={selectedGoalId} onClose={() => setSelectedGoalId(null)} />}
    </div>
  );
}
