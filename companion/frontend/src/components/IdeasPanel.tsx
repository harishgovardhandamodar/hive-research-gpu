import { useCallback, useEffect, useRef, useState } from "react";
import { req } from "../api";
import type { IdeaRunState } from "../types";

function Bar({ label, value }: { label: string; value: number }) {
  return (
    <div className="idea-bar">
      <span className="idea-bar-label">{label}</span>
      <div className="idea-bar-track">
        <div className="idea-bar-fill" style={{ width: `${value * 10}%` }} />
      </div>
      <span className="stat">{value.toFixed(1)}</span>
    </div>
  );
}

function IdeaCards({ ideas }: { ideas: IdeaRunState["ideas"] }) {
  if (ideas.length === 0) return <p className="empty">no archived ideas in this run</p>;
  return (
    <ul className="pool-list">
      {[...ideas]
        .sort((a, b) => b.overall - a.overall)
        .map((i) => (
          <li key={i.title + i.cell} className="pool-card idea-card">
            <div className="pool-head">
              <strong>{i.title}</strong>
              <span className="pill kind">{i.cell}</span>
            </div>
            <p className="pool-abstract">{i.summary}</p>
            <Bar label="novelty" value={i.novelty} />
            <Bar label="feasibility" value={i.feasibility} />
            <Bar label="impact" value={i.impact} />
            {i.verdict && <p className="hint">reviewer: {i.verdict}</p>}
            {i.builds_on && i.builds_on.length > 0 && (
              <p className="hint">builds on: {i.builds_on.join(", ")}</p>
            )}
          </li>
        ))}
    </ul>
  );
}

function exportGroupMd(run: IdeaRunState) {
  const lines = [
    `# Research ideas — ${run.topic}`,
    "",
    `_IDEAgent quality-diversity search · ${run.cells_filled}/${run.archive_cells} archive cells · ${run.candidates_seen} candidates_`,
    "",
    ...[...run.ideas].map(
      (i, idx) =>
        `## ${idx + 1}. ${i.title}\n\n` +
        `\`${i.cell}\` · overall **${i.overall}** · N ${i.novelty}/ F ${i.feasibility}/ I ${i.impact}\n\n` +
        `${i.summary}\n\n` +
        (i.builds_on?.length ? `_builds on: ${i.builds_on.join(", ")}_\n\n` : ""),
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `ideas-${run.topic.slice(0, 40).replace(/\W+/g, "-").toLowerCase()}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function IdeasPanel() {
  const [topic, setTopic] = useState("");
  const [iterations, setIterations] = useState(8);
  const [model, setModel] = useState("fast");
  const [history, setHistory] = useState<IdeaRunState[]>([]);
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await req<{ status: string }>("/api/ideas/latest");
      if (data.status !== "idle" || history.length === 0) {
        const h = await req<IdeaRunState[]>("/api/ideas/history");
        setHistory(h);
        const anyRunning = h.some((r) => r.status === "running");
        if (anyRunning && !pollRef.current) {
          pollRef.current = setInterval(async () => {
            try {
              const hh = await req<IdeaRunState[]>("/api/ideas/history");
              setHistory(hh);
              if (!hh.some((r) => r.status === "running") && pollRef.current) {
                clearInterval(pollRef.current);
                pollRef.current = null;
              }
            } catch {
              /* ignore */
            }
          }, 2500);
        }
      }
    } catch {
      /* ignore */
    }
  }, [history.length]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const start = async () => {
    if (topic.trim().length < 4 || starting) return;
    setStarting(true);
    setErr(null);
    try {
      await req("/api/ideas/run", {
        method: "POST",
        body: JSON.stringify({ topic: topic.trim(), iterations, model }),
      });
      await refresh();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const h = await req<IdeaRunState[]>("/api/ideas/history");
          setHistory(h);
          if (!h.some((r) => r.status === "running") && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch {
          /* ignore */
        }
      }, 2500);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const running = history.some((r) => r.status === "running");

  return (
    <div className="discover">
      <div className="composer-row" style={{ marginTop: 0 }}>
        <input
          className="search"
          style={{ flex: 1 }}
          placeholder="research focus for novel ideas — e.g. 'security evaluation of multi-agent LLM systems'"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !running) void start();
          }}
        />
        <select value={iterations} onChange={(e) => setIterations(Number(e.target.value))} title="QD iterations">
          {[4, 8, 12].map((n) => (
            <option key={n} value={n}>{n} iters</option>
          ))}
        </select>
        <select value={model} onChange={(e) => setModel(e.target.value)} title="ideation model">
          <option value="fast">fast model</option>
          <option value="main">main model</option>
        </select>
        <button onClick={() => void start()} disabled={running || starting || topic.trim().length < 4}>
          {running ? "searching…" : starting ? "…" : "run QD search"}
        </button>
      </div>
      {err && <p className="banner error">{err}</p>}
      {running && <p className="hint">quality-diversity search running… new ideas stream into their group below.</p>}
      {history.length === 0 && !running && (
        <p className="empty">
          Quality-diversity search over your library (IDEAgent-style): each iteration proposes an idea grounded in
          your concepts, judges its novelty/feasibility/impact, and archives the best idea per approach×risk cell.
        </p>
      )}

      {history.map((r, idx) => (
        <details key={r.id} className="idea-group" open={idx === 0}>
          <summary className="idea-group-head">
            <span className={`dot ${r.status === "running" ? "" : r.status === "done" ? "ok" : "bad"}`} />
            <strong className="idea-group-query">{r.topic}</strong>
            <span className="pill kind">{r.status}</span>
            <span className="pill">
              cells {r.cells_filled}/{r.archive_cells}
            </span>
            <span className="stat">{r.candidates_seen} candidates</span>
            <span
              className="ghost"
              role="button"
              title="export this group as markdown"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                exportGroupMd(r);
              }}
            >
              ⬇ md
            </span>
          </summary>
          {r.status === "failed" && r.error && (
            <p className="banner error" style={{ margin: "6px 12px" }}>
              run failed: {r.error}
            </p>
          )}
          {r.status !== "failed" && r.candidates_seen === 0 && r.status === "done" && (
            <p className="empty" style={{ padding: "0 12px 8px" }}>no candidates were produced this run</p>
          )}
          <IdeaCards ideas={r.ideas} />
        </details>
      ))}
    </div>
  );
}
