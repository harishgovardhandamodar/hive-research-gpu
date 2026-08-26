import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState } from "./ui";
import type { TimelineEvent, TimelineResponse, TimelineThread } from "../types";

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

export function TimelineView() {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [query, setQuery] = useState("");
  const [detail, setDetail] = useState<TimelineThread | null>(null);

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
            className={`thread ${STATUS_CLASS[t.status] ?? ""} thread-click`}
            role="button"
            tabIndex={0}
            aria-haspopup="dialog"
            onClick={() => setDetail(t)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setDetail(t);
              }
            }}
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
        {detail && <TimelineDetailOverlay thread={detail} onClose={() => setDetail(null)} />}
      </div>
    </div>
  );
}

type ChronoEntry =
  | { ts: string; kind: "step"; icon: string; headline: string; detail: string }
  | { ts: string; kind: string; icon: string; headline: string; detail: string };

function buildChronology(thread: TimelineThread): ChronoEntry[] {
  const entries: ChronoEntry[] = [];
  if (thread.goal) {
    entries.push({ ts: thread.started, kind: "goal", icon: "\u{1F3AF}", headline: `Goal: ${thread.goal}`, detail: "" });
  }
  for (const s of thread.steps) {
    entries.push({
      ts: s.ts,
      kind: "step",
      icon: s.status === "failed" ? "\u274C" : s.status === "skipped" ? "\u23F8" : "\u2699",
      headline: `${s.tool} — ${s.status}`,
      detail: s.detail || s.summary,
    });
  }
  for (const d of thread.decisions) {
    entries.push({ ts: d.ts, kind: "decision", icon: decisionIcon(d.summary), headline: d.summary, detail: "" });
  }
  for (const e of thread.events as TimelineEvent[]) {
    const icon =
      e.kind === "reflection" ? "\u{1FA9F}" :
      e.kind === "verdict" ? (e.summary.includes("pass") ? "\u2705" : "\u274C") :
      e.kind === "insight" ? "\u{1F4A1}" :
      e.kind === "plan" ? "\u{1F5D2}" : "\u{1F441}";
    entries.push({ ts: e.ts, kind: e.kind, icon, headline: `[${e.kind}] ${e.summary}`, detail: "" });
  }
  return entries.sort((a, b) => a.ts.localeCompare(b.ts));
}

export function TimelineDetailOverlay({ thread, onClose }: { thread: TimelineThread; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const chrono = buildChronology(thread);

  return (
    <div className="kg-overlay" onClick={onClose}>
      <div className="kg-box tl-detail-box" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`Details for ${thread.goal}`}>
        <div className="kg-head">
          <h2>
            {thread.goal.length > 60 ? `${thread.goal.slice(0, 60)}…` : thread.goal}{" "}
            <span className={`pill pill-status status-${thread.status}`}>{thread.status}</span>
            <span className="stat" style={{ marginLeft: 8 }}>
              {fmtSpan(thread.span_s)} · {thread.steps_ok}/{thread.steps.length} steps
              {thread.steps_failed > 0 && `, ${thread.steps_failed} failed`}
              {thread.steps_skipped > 0 && `, ${thread.steps_skipped} skipped`}
            </span>
          </h2>
          <button onClick={onClose}>close</button>
        </div>
        <div className="tl-detail-body">
          {chrono.map((e, i) => (
            <details key={`${e.ts}-${i}`} className="tl-ev" open={i === chrono.length - 1}>
              <summary>
                <span className="tl-ev-icon">{e.icon}</span>
                <span className="node-ts">{e.ts.slice(11, 19)}</span>
                <span className="tl-ev-head">{e.headline}</span>
              </summary>
              {e.kind === "step" && e.headline.split(" — ")[0] && (
                <code className="tl-ev-tool">{e.headline.split(" — ")[0]}</code>
              )}
              {e.detail && e.detail !== e.headline && <pre className="tl-ev-detail">{e.detail}</pre>}
            </details>
          ))}
          {chrono.length === 0 && <EmptyState hint="No recorded events for this run." />}
        </div>
      </div>
    </div>
  );
}
