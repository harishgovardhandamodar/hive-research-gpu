import { useCallback, useEffect, useRef, useState } from "react";
import { req } from "../api";

interface DeepIdea {
  title: string;
  summary: string;
  mechanism?: string;
  chain?: string[];
  builds_on?: string[];
  backward_principle?: string;
  forward_direction?: string;
  revisions: number;
  novelty: number;
  feasibility: number;
  impact: number;
  overall: number;
  verdict?: string;
}

interface DeepRunState {
  id: string;
  topic: string;
  status: "idle" | "running" | "done" | "failed" | "cancelled";
  error?: string | null;
  iterations: number;
  depth: number;
  candidates_seen: number;
  ideas: DeepIdea[];
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

function exportGroupMd(run: DeepRunState) {
  const lines = [
    `# Deep Ideation ideas — ${run.topic}`,
    "",
    `_concept-network traversal · ${run.iterations} pairs · refinement depth ${run.depth}_`,
    "",
    ...[...run.ideas].map(
      (i, idx) =>
        `## ${idx + 1}. ${i.title}\n\n` +
        `**chain:** ${(i.chain ?? []).join(" → ")}\n\n` +
        (i.mechanism ? `**mechanism:** ${i.mechanism}\n\n` : "") +
        `${i.summary}\n\n` +
        (i.backward_principle ? `_backward:_ ${i.backward_principle}\n\n` : "") +
        (i.forward_direction ? `_forward:_ ${i.forward_direction}\n\n` : "") +
        `overall **${i.overall}** · N ${i.novelty}/ F ${i.feasibility}/ I ${i.impact} · revisions ${i.revisions}\n\n`,
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `deepideas-${run.topic.slice(0, 40).replace(/\W+/g, "-").toLowerCase()}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function DeepIdeasPanel() {
  const [topic, setTopic] = useState("");
  const [iterations, setIterations] = useState(5);
  const [depth, setDepth] = useState(2);
  const [model, setModel] = useState("fast");
  const [history, setHistory] = useState<DeepRunState[]>([]);
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await req<{ status: string }>("/api/deepideas/latest");
      if (data.status !== "idle" || history.length === 0) {
        const h = await req<DeepRunState[]>("/api/deepideas/history");
        setHistory(h);
        if (h.some((r) => r.status === "running") && !pollRef.current) {
          pollRef.current = setInterval(async () => {
            try {
              const hh = await req<DeepRunState[]>("/api/deepideas/history");
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

  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
    },
    [],
  );

  const start = async () => {
    if (topic.trim().length < 4 || starting) return;
    setStarting(true);
    setErr(null);
    try {
      await req("/api/deepideas/run", {
        method: "POST",
        body: JSON.stringify({ topic: topic.trim(), iterations, depth, model }),
      });
      await refresh();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const h = await req<DeepRunState[]>("/api/deepideas/history");
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
          placeholder="research focus — deep ideation walks your concept network to bridge distant ideas"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !running) void start();
          }}
        />
        <select value={iterations} onChange={(e) => setIterations(Number(e.target.value))} title="concept pairs explored">
          {[3, 5, 8].map((n) => (
            <option key={n} value={n}>{n} pairs</option>
          ))}
        </select>
        <select value={depth} onChange={(e) => setDepth(Number(e.target.value))} title="recursive refinement rounds per idea">
          {[1, 2, 3].map((n) => (
            <option key={n} value={n}>depth {n}</option>
          ))}
        </select>
        <select value={model} onChange={(e) => setModel(e.target.value)} title="ideation model">
          <option value="fast">fast model</option>
          <option value="main">main model</option>
        </select>
        <button onClick={() => void start()} disabled={running || starting || topic.trim().length < 4}>
          {running ? "traversing…" : starting ? "…" : "run deep ideation"}
        </button>
      </div>
      {err && <p className="banner error">{err}</p>}
      {running && (
        <p className="hint">walking the concept network… backward/forward thinking + recursive refinement per pair.</p>
      )}
      {history.length === 0 && !running && (
        <p className="empty">
          Deep Ideation traverses your library's concept network: it picks seed concepts from your focus,
          bridges them with related neighbours, applies backward/forward thinking, then recursively refines each
          idea against existing work in the library.
        </p>
      )}

      {history.map((r, idx) => (
        <details key={r.id} className="idea-group" open={idx === 0}>
          <summary className="idea-group-head">
            <span className={`dot ${r.status === "running" ? "" : r.status === "done" ? "ok" : "bad"}`} />
            <strong className="idea-group-query">{r.topic}</strong>
            <span className="pill kind">{r.status}</span>
            <span className="pill">{r.iterations} pairs · depth {r.depth}</span>
            <span className="stat">{r.ideas.length} ideas · {r.candidates_seen} explored</span>
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
          {r.ideas.length === 0 ? (
            <p className="empty">no ideas produced in this run{r.error ? ` — ${r.error}` : ""}</p>
          ) : (
            <ul className="pool-list">
              {r.ideas.map((i) => (
                <li key={i.title + i.overall} className="pool-card idea-card">
                  <div className="pool-head">
                    <strong>{i.title}</strong>
                    <span className="pill kind">{i.overall.toFixed(2)}</span>
                  </div>
                  {i.chain && i.chain.length > 0 && (
                    <p className="chain">
                      {(i.chain ?? []).map((c, ci) => (
                        <span key={ci}>
                          {ci > 0 && <span className="chain-arrow"> → </span>}
                          <span className="chip">{c}</span>
                        </span>
                      ))}
                      {typeof i.revisions === "number" && i.revisions > 0 && (
                        <span className="pill">refined ×{i.revisions}</span>
                      )}
                    </p>
                  )}
                  <p className="pool-abstract">{i.summary}</p>
                  {i.mechanism && <p className="hint">mechanism: {i.mechanism}</p>}
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
          )}
        </details>
      ))}
    </div>
  );
}
