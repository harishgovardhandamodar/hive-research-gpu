import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ArtifactNode, KGData } from "../types";

interface SimNode {
  id: string;
  label: string;
  type: string;
  seed?: boolean;
  definition?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const PAPER_COLOR = "#60a5fa";
const CONCEPT_COLOR = "#c084fc";

// Same relation semantics as the hive research app's knowledge graph
// (dashboard.html): each edge type gets its own color / width / dash.
type RelStyle = { color: string; width: number; dash: number[] | null };
const REL_COLORS: Record<string, RelStyle> = {
  cites: { color: "#34d399", width: 1.8, dash: null },
  extends: { color: "#c084fc", width: 1.6, dash: null },
  improves: { color: "#22d3ee", width: 1.6, dash: null },
  uses: { color: "#60a5fa", width: 1.3, dash: null },
  introduces: { color: "#fbbf24", width: 1.4, dash: null },
  proposes: { color: "#fbbf24", width: 1.2, dash: null },
  compares: { color: "#f472b6", width: 1.1, dash: [3, 3] },
  contrasts: { color: "#f87171", width: 1.2, dash: [3, 3] },
  references: { color: "#64748b", width: 1, dash: [2, 3] },
  nests: { color: "#a78bfa", width: 1.1, dash: null },
  related_to: { color: "#334155", width: 0.9, dash: [2, 4] },
};

function relStyle(relation: string | undefined): RelStyle {
  return REL_COLORS[relation ?? ""] ?? REL_COLORS.related_to;
}

/** On the light theme the navy default disappears — brighten it. */
function themeEdgeColor(style: RelStyle): RelStyle {
  if (document.documentElement.dataset.theme === "light" && style === REL_COLORS.related_to) {
    return { ...style, color: "#94a3b8" };
  }
  return style;
}

function simulate(nodes: SimNode[], links: { source: string; target: string }[], width: number, height: number) {
  const index = new Map(nodes.map((n) => [n.id, n]));
  const R = Math.min(width, height) * 0.38;
  nodes.forEach((n, i) => {
    if (n.x !== 0 || n.y !== 0) return;
    const a = (i / nodes.length) * Math.PI * 2;
    n.x = width / 2 + R * Math.cos(a);
    n.y = height / 2 + R * Math.sin(a);
  });
  for (let tick = 0; tick < 300; tick++) {
    // repulsion (O(n²), fine at ≤ ~300 nodes)
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d2 = 1;
        }
        if (d2 > 40000) continue; // cut long-range work
        const f = 1800 / d2;
        const d = Math.sqrt(d2);
        a.vx += (dx / d) * f;
        a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f;
        b.vy -= (dy / d) * f;
      }
    }
    // link springs
    for (const l of links) {
      const a = index.get(l.source);
      const b = index.get(l.target);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const rest = 90;
      const f = ((d - rest) / d) * 0.04;
      a.vx += dx * f;
      a.vy += dy * f;
      b.vx -= dx * f;
      b.vy -= dy * f;
    }
    // gravity + integrate
    let energy = 0;
    for (const n of nodes) {
      n.vx += (width / 2 - n.x) * 0.0035;
      n.vy += (height / 2 - n.y) * 0.0035;
      n.vx *= 0.86;
      n.vy *= 0.86;
      n.x += Math.max(-12, Math.min(12, n.vx));
      n.y += Math.max(-12, Math.min(12, n.vy));
      energy += n.vx * n.vx + n.vy * n.vy;
    }
    if (energy < 4) break;
  }
}

export function KnowledgeGraph({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<KGData | null>(null);
  const [mode, setMode] = useState<{ kind: "full" | "search"; q?: string }>({ kind: "full" });
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hover, setHover] = useState<SimNode | null>(null);
  const hoverRef = useRef<SimNode | null>(null);
  const [canvasRef, setCanvasRef] = useState<HTMLCanvasElement | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const simRef = useRef<SimNode[]>([]);
  const linkRef = useRef<{ source: string; target: string; relation: string }[]>([]);

  // modal hygiene: Escape closes, search field gets focus on open
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    searchRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const loadFull = useCallback(async () => {
    try {
      setData(await api.kg());
      setError(null);
      setMode({ kind: "full" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load knowledge graph");
    }
  }, []);

  useEffect(() => {
    loadFull();
  }, [loadFull]);

  useEffect(() => {
    if (!data || !canvasRef) return;
    const canvas = canvasRef;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * devicePixelRatio;
    canvas.height = height * devicePixelRatio;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const nodes: SimNode[] = data.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      type: n.type,
      seed: n.seed,
      definition: n.definition,
      x: 0,
      y: 0,
      vx: 0,
      vy: 0,
    }));
    simRef.current = nodes;
    linkRef.current = data.links;

    simulate(nodes, data.links, width, height);

    let raf = 0;
    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      const pos = new Map(nodes.map((n) => [n.id, n]));
      const h = hoverRef.current;
      for (const l of data.links) {
        const a = pos.get(l.source);
        const b = pos.get(l.target);
        if (!a || !b) continue;
        const style = themeEdgeColor(relStyle(l.relation));
        const touched = h && (l.source === h.id || l.target === h.id);
        ctx.strokeStyle = touched ? "#f0b429" : style.color;
        ctx.lineWidth = style.width * (touched ? 1.6 : 1);
        ctx.setLineDash(style.dash ?? []);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      for (const n of nodes) {
        const isPaper = n.type === "paper";
        ctx.beginPath();
        ctx.arc(n.x, n.y, isPaper ? 4.5 : 3.5, 0, Math.PI * 2);
        ctx.fillStyle = isPaper ? PAPER_COLOR : CONCEPT_COLOR;
        if (n.seed) {
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1.4;
        }
        ctx.fill();
        if (n.seed) ctx.stroke();
      }
      raf = requestAnimationFrame(draw);
    };
    draw();

    const onMove = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      let best: SimNode | null = null;
      let bestD = 100;
      for (const n of nodes) {
        const d = (n.x - mx) ** 2 + (n.y - my) ** 2;
        if (d < bestD) {
          bestD = d;
          best = n;
        }
      }
      hoverRef.current = best;
      setHover(best);
    };
    canvas.addEventListener("mousemove", onMove);
    return () => {
      cancelAnimationFrame(raf);
      canvas.removeEventListener("mousemove", onMove);
    };
  }, [data]);

  const runSearch = async () => {
    if (query.trim().length < 2) {
      await loadFull();
      return;
    }
    try {
      const result = await api.kgSearch(query.trim());
      setData(result);
      setError(null);
      setMode({ kind: "search", q: query.trim() });
    } catch (e) {
      setError(e instanceof Error ? e.message : "graph search failed");
    }
  };

  const openPaperNotes = (node: ArtifactNode | undefined) => {
    if (!node) return;
  };
  void openPaperNotes;

  return (
    <div className="kg-overlay" onClick={onClose}>
      <div className="kg-box" onClick={(e) => e.stopPropagation()}>
        <div className="kg-head">
          <h2>
            Knowledge Graph{" "}
            <span className="badge">{data?.nodes.length ?? 0} nodes</span>
            <span className="stat" style={{ marginLeft: 8 }}>
              {mode.kind === "search" ? `sub-graph for “${mode.q}”` : "global view"}
            </span>
          </h2>
          <button onClick={onClose}>close</button>
        </div>
        {error && (
          <div className="banner error" style={{ margin: "8px 14px" }}>
            <span>{error}</span>
            <button className="ghost" onClick={() => void loadFull()}>retry</button>
          </div>
        )}
        <div className="composer-row" style={{ margin: "0 14px" }}>
          <input
            className="search"
            placeholder="search the graph — e.g. agent security, federated learning…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch();
            }}
          />
          <button onClick={() => void runSearch()}>search sub-graph</button>
          {mode.kind === "search" && (
            <button className="ghost" onClick={() => void loadFull()}>
              reset
            </button>
          )}
        </div>
        <div className="kg-canvas-wrap">
          <canvas ref={setCanvasRef} className="kg-canvas" />
          {hover && (
            <div className="kg-tooltip">
              <strong>{hover.label}</strong>
              <span className="pill kind">{hover.type}</span>
              {hover.seed && <span className="pill">match</span>}
              {hover.definition && <p>{hover.definition}</p>}
            </div>
          )}
          <div className="kg-legend">
            <span><i style={{ background: PAPER_COLOR }} /> papers</span>
            <span><i style={{ background: CONCEPT_COLOR }} /> concepts</span>
            <span><i style={{ background: REL_COLORS.cites.color }} /> cites</span>
            <span><i style={{ background: REL_COLORS.extends.color }} /> extends</span>
            <span><i style={{ background: REL_COLORS.related_to.color }} /> related</span>
          </div>
        </div>
      </div>
    </div>
  );
}
