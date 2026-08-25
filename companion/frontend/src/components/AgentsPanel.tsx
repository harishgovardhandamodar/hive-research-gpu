import { useCallback, useEffect, useMemo, useState } from "react";
import { req } from "../api";
import { EmptyState } from "./ui";

interface Agent {
  id: string;
  name: string;
  category: string;
  tagline: string;
  description: string;
  paper_title: string;
  paper_url: string;
  arxiv_id: string | null;
  capabilities: string[];
  workflow: string[];
  icon: string;
  color: string;
  implemented: boolean;
  autonomy: string;
  tags: string[];
  enabled: boolean;
  from_fork?: boolean;
}

const CATEGORY_ORDER = ["ideation", "experimentation", "writing"] as const;
const CATEGORY_LABEL: Record<string, string> = {
  ideation: "Idea Generation",
  experimentation: "Experimentation",
  writing: "Writing & Review",
};
const CATEGORY_ICON: Record<string, string> = {
  ideation: "💡",
  experimentation: "🔬",
  writing: "📝",
};

export function AgentsPanel() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [category, setCategory] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [forkExtra, setForkExtra] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await req<{ agents: Agent[]; selected_ids: string[]; categories: Record<string, string>; fork_extra?: number }>("/api/agents");
      setAgents(data.agents);
      setSelected(data.selected_ids);
      setForkExtra(data.fork_extra ?? 0);
    } catch {
      /* ignore */
    }
  }, []);

  const syncFromFork = async () => {
    setSyncing(true);
    try {
      await req<{ count: number }>("/api/agents/refresh", { method: "POST", body: "{}" });
      await load();
    } catch {
      /* ignore */
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30000);
    return () => clearInterval(t);
  }, [load]);

  const toggle = async (id: string) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    // keep at least one
    if (next.length === 0) return;
    setBusy(id);
    try {
      const res = await req<{ selected_ids: string[] }>("/api/agents/selection", {
        method: "POST",
        body: JSON.stringify({ selected_ids: next }),
      });
      setSelected(res.selected_ids);
      setAgents((prev) => prev.map((a) => ({ ...a, enabled: res.selected_ids.includes(a.id) })));
    } catch {
      /* ignore */
    } finally {
      setBusy(null);
    }
  };

  const useAgent = (a: Agent) => {
    const text = `Use ${a.name} workflow: ${a.workflow.join(" → ")} — ${a.tagline}. Goal: `;
    window.dispatchEvent(new CustomEvent("fox-prefill", { detail: text }));
    // also ensure it's enabled
    if (!selected.includes(a.id)) void toggle(a.id);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return agents.filter((a) => {
      if (category !== "all" && a.category !== category) return false;
      if (!q) return true;
      return (
        a.name.toLowerCase().includes(q) ||
        a.tagline.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        a.paper_title.toLowerCase().includes(q) ||
        a.tags.some((t) => t.toLowerCase().includes(q)) ||
        a.capabilities.some((c) => c.toLowerCase().includes(q))
      );
    });
  }, [agents, category, query]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: agents.length };
    for (const cat of CATEGORY_ORDER) c[cat] = agents.filter((a) => a.category === cat).length;
    return c;
  }, [agents]);

  return (
    <div className="panel agents-panel">
      <div className="agent-head">
        <h2>
          Agent Collection
          <span className="badge" title="enabled agents">
            {selected.length} active
          </span>
        </h2>
        <p className="hint">
          Pick the agents that fit your workflow. Curated from your fork{" "}
          <a href="https://github.com/harishgovardhandamodar/ai-agent-papers/blob/main/applications/domain/ai-scientist.md" target="_blank" rel="noreferrer">
            harishgovardhandamodar/ai-agent-papers
          </a>{" "}
          (upstream: masamasa59) — 3 tracks. The planner prioritizes your active agents&apos; toolchains.
          {forkExtra > 0 && <span> · <em>{forkExtra} extra from fork</em></span>}
        </p>
        <div className="agent-sync-row">
          <button className="ghost" onClick={() => void syncFromFork()} disabled={syncing} title="Fetch your fork's ai-scientist.md and sync — any edit to your fork auto-reflects here">
            {syncing ? "syncing…" : "↻ Sync from fork"}
          </button>
          <span className="hint">or run <code>python companion/scripts/sync_agents_from_fork.py</code></span>
        </div>
      </div>

      <div className="agent-toolbar">
        <input className="search agent-search" placeholder="search agents, capabilities, tags…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="agent-cats">
          {(["all", ...CATEGORY_ORDER] as const).map((cat) => (
            <button
              key={cat}
              className={category === cat ? "chip chip-active" : "chip"}
              onClick={() => setCategory(cat)}
              title={cat === "all" ? "all agents" : CATEGORY_LABEL[cat]}
            >
              {cat === "all" ? "All" : `${CATEGORY_ICON[cat]} ${CATEGORY_LABEL[cat]}`} · {counts[cat] ?? 0}
            </button>
          ))}
        </div>
      </div>

      <div className="agent-grid">
        {filtered.length === 0 && <EmptyState hint="No agents match your filter." />}
        {filtered.map((a) => (
          <div key={a.id} className={a.enabled ? "agent-card enabled" : "agent-card"} style={{ borderLeftColor: a.color }}>
            <div className="agent-card-head">
              <span className="agent-icon" style={{ background: `${a.color}18`, borderColor: `${a.color}40` }}>
                {a.icon}
              </span>
              <div className="agent-title-wrap">
                <strong className="agent-name">{a.name}</strong>
                <span className="agent-tagline">{a.tagline}</span>
              </div>
              <label className="agent-toggle" title={a.enabled ? "active — click to disable" : "click to enable"}>
                <input type="checkbox" checked={a.enabled} disabled={busy === a.id} onChange={() => void toggle(a.id)} />
                <span className="toggle-track" />
              </label>
            </div>

            <p className="agent-desc">{a.description}</p>

            <div className="agent-meta">
              <span className="pill" style={{ borderColor: a.color, color: a.color }}>
                {CATEGORY_ICON[a.category]} {a.category}
              </span>
              <span className="pill" title="recommended autonomy">
                {a.autonomy}
              </span>
              {a.implemented && <span className="pill kind">implemented</span>}
              {a.from_fork && <span className="pill" style={{ borderColor: "#b08bd4", color: "#b08bd4" }}>from fork</span>}
              <a className="agent-paper" href={a.paper_url} target="_blank" rel="noreferrer" title={a.paper_title}>
                {a.arxiv_id ? `arXiv:${a.arxiv_id}` : "paper"} ↗
              </a>
            </div>

            <div className="agent-chips">
              {a.capabilities.map((c) => (
                <span key={c} className="chip chip-sm">
                  {c}
                </span>
              ))}
            </div>

            <div className="agent-workflow" title={a.workflow.join(" → ")}>
              {a.workflow.map((step, i) => (
                <span key={step} className="wf-step">
                  {i > 0 && <span className="wf-arrow">→</span>}
                  {step}
                </span>
              ))}
            </div>

            <div className="agent-actions">
              <button className="ghost" onClick={() => useAgent(a)} title="Prefill goal composer with this agent's workflow">
                use workflow
              </button>
              <a href={a.paper_url} target="_blank" rel="noreferrer" className="ghost" style={{ textDecoration: "none", padding: "6px 10px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}>
                read paper
              </a>
            </div>
          </div>
        ))}
      </div>

      <p className="hint" style={{ marginTop: 10 }}>
        Tip: enable 2–4 agents that cover your current phase (e.g. <em>ResearchAgent + IDEAgent</em> for ideation, <em>AI Scientist + SAGA</em> for long-horizon runs). The companion will bias the planner toward their workflows.
      </p>
    </div>
  );
}
