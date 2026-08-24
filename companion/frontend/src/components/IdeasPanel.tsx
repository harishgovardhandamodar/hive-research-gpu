import { useCallback, useEffect, useRef, useState } from "react";
import { req } from "../api";

interface Idea {
  title: string;
  summary: string;
  approach: string;
  risk: string;
  novelty: number;
  feasibility: number;
  impact: number;
  overall: number;
  verdict?: string;
  builds_on?: string[];
  cell: string;
}

interface IdeaRunState {
  id: string;
  topic: string;
  status: "idle" | "running" | "done" | "failed" | "cancelled";
  error?: string | null;
  iterations: number;
  archive_cells: number;
  cells_filled: number;
  candidates_seen: number;
  ideas: Idea[];
}

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

export function IdeasPanel() {
  const [topic, setTopic] = useState("");
  const [iterations, setIterations] = useState(8);
  const [model, setModel] = useState("fast");
  const [run, setRun] = useState<IdeaRunState | null>(null);
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const latest = await req<IdeaRunState>("/api/ideas/latest");
      if (latest.status !== "idle") {
        setRun(latest);
        if (latest.status === "running" && !pollRef.current) {
          pollRef.current = setInterval(async () => {
            try {
              const r = await req<IdeaRunState>("/api/ideas/latest");
              setRun(r);
              if (r.status !== "running" && pollRef.current) {
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
  }, []);

  useEffect(() => {
    void poll();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [poll]);

  const start = async () => {
    if (topic.trim().length < 4 || starting) return;
    setStarting(true);
    setErr(null);
    try {
      const r = await req<IdeaRunState>("/api/ideas/run", {
        method: "POST",
        body: JSON.stringify({ topic: topic.trim(), iterations, model }),
      });
      setRun(r);
      pollRef.current = setInterval(async () => {
        try {
          const latest = await req<IdeaRunState>("/api/ideas/latest");
          setRun(latest);
          if (latest.status !== "running" && pollRef.current) {
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

  const running = run?.status === "running";
  const exportMd = () => {
    if (!run) return;
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
  };

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
        {run && run.ideas.length > 0 && (
          <button onClick={exportMd} title="export ranked ideas as markdown">⬇ md</button>
        )}
      </div>
      {err && <p className="banner error">{err}</p>}
      {run && (
        <p className="hint" style={{ marginBottom: 6 }}>
          status: <strong>{run.status}</strong> · archive {run.cells_filled}/{run.archive_cells} cells ·{" "}
          {run.candidates_seen} candidates generated
          {run.error ? ` · ${run.error}` : ""}
        </p>
      )}
      {!run && (
        <p className="empty">
          Quality-diversity search over your library (IDEAgent-style): each iteration proposes an idea grounded in
          your concepts, judges its novelty/feasibility/impact, and archives the best idea per approach×risk cell —
          filling rare cells pushes toward genuinely diverse, bolder ideas.
        </p>
      )}
      <ul className="pool-list">
        {[...(run?.ideas ?? [])]
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
    </div>
  );
}
