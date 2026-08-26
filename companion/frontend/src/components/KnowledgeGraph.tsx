import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { KGData, ScientistCorpus } from "../types";

interface SimNode {
  id: string;
  label: string;
  type: string;
  seed?: boolean;
  definition?: string;
  abstract?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface Tip {
  d: SimNode;
  relations: { rel: string; dir: "<-" | "->"; other: SimNode }[];
  sx: number;
  sy: number;
  pinned: boolean;
}

const PAPER_COLOR = "#60a5fa";
const CONCEPT_COLOR = "#c084fc";
const LINEAGE_COLOR = "#2dd4bf";
const SCIENTIST_COLOR = "#fb923c"; // Awesome-AI-Scientist corpus nodes
const LABEL_COLOR = "#94a3b8";
const LINEAGE_RELS = new Set(["cites", "extends", "improves", "proposes"]);
const PAPER_SIZE = 14;
const CONCEPT_SIZE = 7;

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
  // dashboard navy is invisible on the companion panel; lifted slate instead
  related_to: { color: "#7d8ca3", width: 1.15, dash: [2, 4] },
};

function relStyle(relation: string | undefined): RelStyle {
  return REL_COLORS[relation ?? ""] ?? REL_COLORS.related_to;
}

/** On the light theme the default slate disappears — brighten it. */
function themeEdgeColor(style: RelStyle): RelStyle {
  if (document.documentElement.dataset.theme === "light" && style === REL_COLORS.related_to) {
    return { ...style, color: "#94a3b8" };
  }
  return style;
}

/** One tick of the live d3-style simulation; caller drives alpha decay. */
function physicsTick(
  nodes: SimNode[],
  links: { source: string; target: string }[],
  width: number,
  height: number,
  alpha: number,
) {
  const index = new Map(nodes.map((n) => [n.id, n]));
  // many-body repulsion — papers push harder than concepts
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) {
        dx = Math.random() - 0.5;
        dy = Math.random() - 0.5;
        d2 = 1;
      }
      const strength = a.type === "paper" || b.type === "paper" ? -320 : -160;
      const f = (strength * alpha) / d2;
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
    const target = 110;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 1;
    const f = ((d - target) / d) * 0.3 * alpha;
    a.vx += dx * f;
    a.vy += dy * f;
    b.vx -= dx * f;
    b.vy -= dy * f;
  }
  // soft center gravity
  const cx = width / 2;
  const cy = height / 2;
  for (const n of nodes) {
    n.vx += (cx - n.x) * 0.0016 * alpha;
    n.vy += (cy - n.y) * 0.0016 * alpha;
  }
  // collision separation so labels/nodes don't stack
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      const min = (a.type === "paper" ? PAPER_SIZE : CONCEPT_SIZE * 2) + (b.type === "paper" ? PAPER_SIZE : CONCEPT_SIZE * 2);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d2 = dx * dx + dy * dy;
      if (d2 < min * min && d2 > 0.01) {
        const d = Math.sqrt(d2);
        const push = ((min - d) / d) * 0.22;
        a.vx -= dx * push;
        a.vy -= dy * push;
        b.vx += dx * push;
        b.vy += dy * push;
      }
    }
  }
  // integrate with d3-like velocity decay; pinned nodes stay put
  for (const n of nodes) {
    if ((n as SimNode & { pinned?: boolean }).pinned) {
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx *= 0.62;
    n.vy *= 0.62;
    n.x += n.vx;
    n.y += n.vy;
    n.x = Math.max(10, Math.min(width - 10, n.x));
    n.y = Math.max(10, Math.min(height - 10, n.y));
  }
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(x, y, w, h, r);
  } else {
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
}

export function KnowledgeGraph({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<KGData | null>(null);
  const [mode, setMode] = useState<{ kind: "full" | "search"; q?: string }>({ kind: "full" });
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [relFilter, setRelFilter] = useState("all");
  const [showLabels, setShowLabels] = useState(true);
  const [showRelLabels, setShowRelLabels] = useState(true);
  const [tip, setTip] = useState<Tip | null>(null);

  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null);
  const scientistRef = useRef<ScientistCorpus | null>(null);
  const tldrCacheRef = useRef<Map<string, string>>(new Map());
  const [, forceTick] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const simNodesRef = useRef<SimNode[]>([]);
  const linksRef = useRef<{ source: string; target: string; relation?: string }[]>([]);
  const posRef = useRef<Map<string, { x: number; y: number }>>(new Map()); // persists layout across refreshes
  const viewRef = useRef({ x: 0, y: 0, k: 1 });
  const alphaRef = useRef({ a: 0.9, target: 0 }); // live simulation energy
  const tipRef = useRef<Tip | null>(null);
  const dragRef = useRef<{
    kind: "none" | "pan" | "node";
    id?: string;
    offX: number;
    offY: number;
    moved: boolean;
    lastX: number;
    lastY: number;
  }>({ kind: "none", offX: 0, offY: 0, moved: false, lastX: 0, lastY: 0 });

  const settingsRef = useRef({ relFilter, showLabels, showRelLabels });
  settingsRef.current = { relFilter, showLabels, showRelLabels };

  // modal hygiene: Escape closes, search gets focus, Tab stays inside the modal
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const box = wrapRef.current;
      if (!box) return;
      const focusables = box.querySelectorAll<HTMLElement>(
        'button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
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

  // AI-Scientist corpus tagging: base arxiv id -> excerpt metadata
  useEffect(() => {
    api
      .scientistExcerpts()
      .then((payload) => {
        const byId: ScientistCorpus["byId"] = {};
        for (const e of payload.excerpts ?? []) {
          if (e.arxiv_id) byId[e.arxiv_id.split("v")[0]] = { ...e };
        }
        const corpus = { byId, totalWithArxiv: payload.total_with_arxiv ?? 0, remaining: payload.remaining ?? 0 };
        scientistRef.current = corpus;
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!data || !canvasEl) return;
    const canvas = canvasEl;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * devicePixelRatio;
    canvas.height = height * devicePixelRatio;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // reuse persisted positions so toggling options doesn't reshuffle the layout
    const nodes: SimNode[] = data.nodes.map((n) => {
      const prev = posRef.current.get(n.id);
      return {
        id: n.id,
        label: n.label,
        type: n.type,
        seed: !!n.seed,
        definition: (n as { definition?: string }).definition,
        x: prev?.x ?? 0,
        y: prev?.y ?? 0,
        vx: 0,
        vy: 0,
      };
    });
    const index = new Map(nodes.map((n) => [n.id, n]));
    simNodesRef.current = nodes;
    linksRef.current = data.links;
    // ring placement for brand-new nodes, then let the LIVE simulation
    // unfold the layout organically (alpha decays each frame)
    const R = Math.min(width, height) * 0.38;
    nodes.forEach((n, i) => {
      if (n.x === 0 && n.y === 0) {
        const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
        n.x = width / 2 + R * Math.cos(a);
        n.y = height / 2 + R * Math.sin(a);
      }
    });
    for (const n of nodes) posRef.current.set(n.id, { x: n.x, y: n.y });
    alphaRef.current.a = Math.max(alphaRef.current.a, 0.9);

    const citedIds = new Set(data.links.filter((l) => l.relation === "cites").map((l) => l.target));

    const neighborsOf = (id: string) => {
      const out: { rel: string; dir: "<-" | "->"; other: SimNode }[] = [];
      for (const l of data.links) {
        if (l.source === id && index.has(l.target))
          out.push({ rel: l.relation ?? "related_to", dir: "->", other: index.get(l.target)! });
        else if (l.target === id && index.has(l.source))
          out.push({ rel: l.relation ?? "related_to", dir: "<-", other: index.get(l.source)! });
      }
      return out;
    };

    const drawArrow = (ax: number, ay: number, bx: number, by: number, shrink: number, color: string) => {
      const ang = Math.atan2(by - ay, bx - ax);
      const tx = bx - Math.cos(ang) * shrink;
      const ty = by - Math.sin(ang) * shrink;
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      const s = 5.5;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(tx - s * Math.cos(ang - 0.42), ty - s * Math.sin(ang - 0.42));
      ctx.lineTo(tx - s * Math.cos(ang + 0.42), ty - s * Math.sin(ang + 0.42));
      ctx.closePath();
      ctx.fill();
    };

    const nodeHitRadius = (n: SimNode) => (n.type === "paper" ? PAPER_SIZE : CONCEPT_SIZE) + 4;

    const draw = () => {
      // live physics: alpha cools each frame; drags and data changes re-heat it
      const alphaObj = alphaRef.current;
      alphaObj.a += (alphaObj.target - alphaObj.a) * 0.028;
      if (alphaObj.a > 0.004) {
        physicsTick(nodes, data.links, width, height, alphaObj.a);
        for (const n of nodes) posRef.current.set(n.id, { x: n.x, y: n.y });
      }
      const view = viewRef.current;
      const { relFilter: rf, showLabels: sl, showRelLabels: srl } = settingsRef.current;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.translate(view.x, view.y);
      ctx.scale(view.k, view.k);

      const h = tipRef.current && tipRef.current.pinned ? tipRef.current.d : null;
      const pos = new Map(nodes.map((n) => [n.id, n]));

      // edges: relation color/width/dash, lineage opacity, arrows, focus dimming
      for (const l of data.links) {
        const a = pos.get(l.source);
        const b = pos.get(l.target);
        if (!a || !b) continue;
        if (rf !== "all" && (l.relation ?? "related_to") !== rf) continue;
        const style = themeEdgeColor(relStyle(l.relation));
        const touched = h && (l.source === h.id || l.target === h.id);
        const baseAlpha = LINEAGE_RELS.has(l.relation ?? "") ? 0.75 : 0.5;
        ctx.globalAlpha = h ? (touched ? Math.min(1, baseAlpha + 0.25) : 0.06) : baseAlpha;
        drawArrow(a.x, a.y, b.x, b.y, nodeHitRadius(b), touched ? "#f0b429" : style.color);
        ctx.lineWidth = style.width * (touched ? 1.6 : 1);
        ctx.setLineDash(style.dash ?? []);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      // relation labels: rotated chip at the edge midpoint
      if (srl) {
        ctx.font = "8px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        for (const l of data.links) {
          if (rf !== "all" && (l.relation ?? "related_to") !== rf) continue;
          const a = pos.get(l.source);
          const b = pos.get(l.target);
          if (!a || !b) continue;
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          let ang = (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI;
          if (ang > 90 || ang < -90) ang += 180;
          const style = themeEdgeColor(relStyle(l.relation));
          ctx.save();
          ctx.translate(mx, my);
          ctx.rotate((ang * Math.PI) / 180);
          const text = l.relation ?? "";
          const w = ctx.measureText(text).width + 8;
          ctx.globalAlpha = h ? 0.85 : 0.9;
          ctx.fillStyle = "#1e293b";
          roundRect(ctx, -w / 2, -7, w, 14, 4);
          ctx.fill();
          ctx.strokeStyle = "#1e3a5f";
          ctx.lineWidth = 0.5;
          ctx.stroke();
          ctx.fillStyle = style.color;
          ctx.fillText(text, 0, 0);
          ctx.restore();
        }
        ctx.globalAlpha = 1;
      }

      // nodes: rounded squares for papers (teal when cited), circles for concepts
      for (const n of nodes) {
        const cited = citedIds.has(n.id);
        const sciEntry =
          n.type === "paper" ? scientistRef.current?.byId[n.id.split("v")[0]] : undefined;
        const fill = sciEntry
          ? SCIENTIST_COLOR
          : n.type === "paper"
            ? (cited ? LINEAGE_COLOR : PAPER_COLOR)
            : CONCEPT_COLOR;
        const dimmed = h && n.id !== h.id && !data.links.some(
          (l) => (l.source === h!.id && l.target === n.id) || (l.target === h!.id && l.source === n.id),
        );
        ctx.globalAlpha = dimmed ? 0.2 : 1;
        if (n.type === "paper") {
          ctx.fillStyle = fill;
          ctx.strokeStyle = fill;
          ctx.lineWidth = 2;
          ctx.globalAlpha *= 0.999;
          roundRect(ctx, n.x - PAPER_SIZE / 2, n.y - PAPER_SIZE / 2, PAPER_SIZE, PAPER_SIZE, 4);
          ctx.fill();
          ctx.globalAlpha = dimmed ? 0.2 : 0.5;
          ctx.stroke();
          ctx.globalAlpha = dimmed ? 0.2 : 1;
        } else {
          ctx.beginPath();
          ctx.arc(n.x, n.y, CONCEPT_SIZE, 0, Math.PI * 2);
          ctx.fillStyle = fill;
          ctx.fill();
          ctx.strokeStyle = fill;
          ctx.lineWidth = 2;
          ctx.globalAlpha = dimmed ? 0.2 : 0.5;
          ctx.stroke();
          ctx.globalAlpha = dimmed ? 0.2 : 1;
        }
        if (n.seed) {
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.arc(n.x, n.y, CONCEPT_SIZE + 3, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (sl) {
          ctx.font = "10px system-ui, sans-serif";
          ctx.fillStyle = LABEL_COLOR;
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText((n.label ?? "").slice(0, 25), n.x + PAPER_SIZE / 2 + 6, n.y);
        }
      }
      ctx.globalAlpha = 1;

      raf = requestAnimationFrame(draw);
    };
    let raf = requestAnimationFrame(draw);
    // ── pointer interactions: hover tooltip, click pin, node drag, pan, zoom ──
    const toWorld = (mx: number, my: number) => {
      const v = viewRef.current;
      return { x: (mx - v.x) / v.k, y: (my - v.y) / v.k };
    };
    const pick = (wx: number, wy: number) => {
      let best: SimNode | null = null;
      let bestD = Infinity;
      for (const n of nodes) {
        const d = (n.x - wx) ** 2 + (n.y - wy) ** 2;
        if (d < bestD && d < nodeHitRadius(n) ** 2) {
          bestD = d;
          best = n;
        }
      }
      return best;
    };

    const onMouseMove = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      const world = toWorld(mx, my);
      const drag = dragRef.current;

      if (drag.kind === "node" && drag.id) {
        const n = index.get(drag.id);
        if (n) {
          n.x = world.x - drag.offX;
          n.y = world.y - drag.offY;
          n.vx = 0;
          n.vy = 0;
          (n as SimNode & { pinned?: boolean }).pinned = true;
          posRef.current.set(n.id, { x: n.x, y: n.y });
          // dragging stirs the simulation — keep it hot while held
          alphaRef.current.target = 0.32;
          alphaRef.current.a = Math.max(alphaRef.current.a, 0.32);
        }
        return;
      }
      if (drag.kind === "pan") {
        viewRef.current.x += ev.clientX - drag.lastX;
        viewRef.current.y += ev.clientY - drag.lastY;
        drag.lastX = ev.clientX;
        drag.lastY = ev.clientY;
        drag.moved = true;
        return;
      }

      const hit = pick(world.x, world.y);
      if (hit) {
        setTip({
          d: hit,
          relations: neighborsOf(hit.id),
          sx: mx,
          sy: my,
          pinned: !!(tipRef.current?.pinned && tipRef.current.d.id === hit.id),
        });
        canvas.style.cursor = "pointer";
      } else {
        if (tipRef.current?.pinned) setTip(tipRef.current);
        else setTip(null);
        canvas.style.cursor = "default";
      }
      void my_unused(ev);
    };
    const my_unused = (_ev: MouseEvent) => undefined;

    const onMouseDown = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const world = toWorld(ev.clientX - rect.left, ev.clientY - rect.top);
      const hit = pick(world.x, world.y);
      dragRef.current = {
        kind: hit ? "node" : "pan",
        id: hit?.id,
        offX: hit ? world.x - hit.x : 0,
        offY: hit ? world.y - hit.y : 0,
        moved: false,
        lastX: ev.clientX,
        lastY: ev.clientY,
      };
    };

    const onMouseUp = (ev: MouseEvent) => {
      const drag = dragRef.current;
      dragRef.current = { kind: "none", offX: 0, offY: 0, moved: false, lastX: 0, lastY: 0 };
      // release the heat: simulation cools back down after stirring
      alphaRef.current.target = 0;
      if (drag.moved || drag.kind === "none") return;
      const rect = canvas.getBoundingClientRect();
      const world = toWorld(ev.clientX - rect.left, ev.clientY - rect.top);
      const hit = pick(world.x, world.y);
      if (!hit) {
        setTip(null);
        tipRef.current = null;
        return;
      }
      // click pins/unpins the preview like the dashboard's showNodePreview
      setTip((cur) =>
        cur && cur.pinned && cur.d.id === hit.id ? null : { d: hit, relations: neighborsOf(hit.id), sx: ev.clientX - rect.left, sy: ev.clientY - rect.top, pinned: true },
      );
    };

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      const v = viewRef.current;
      const factor = Math.pow(1.0016, -ev.deltaY);
      const k = Math.max(0.1, Math.min(8, v.k * factor));
      v.x = mx - ((mx - v.x) * k) / v.k;
      v.y = my - ((my - v.y) * k) / v.k;
      v.k = k;
    };

    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      cancelAnimationFrame(raf);
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mouseup", onMouseUp);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [data]);

  // keep the frozen tooltip ref in sync for the animation loop
  useEffect(() => {
    tipRef.current = tip;
  }, [tip]);

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

  const relationsPresent = [...new Set((data?.links ?? []).map((l) => l.relation || "related_to"))].sort();

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
            ref={searchRef}
            className="search"
            placeholder="search the graph — e.g. agent security, federated learning…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch();
            }}
          />
          <select value={relFilter} onChange={(e) => setRelFilter(e.target.value)} title="filter edges by relation type">
            <option value="all">all edges</option>
            {relationsPresent.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
            <option value="__none">hide edges</option>
          </select>
          <select value="" onChange={(e) => { if (e.target.value === "labels") setShowLabels((v) => !v); if (e.target.value === "rellabels") setShowRelLabels((v) => !v); e.target.value = ""; }} title="toggle overlays">
            <option value="" disabled>view ▾</option>
            <option value="labels">{showLabels ? "✓ node labels" : "node labels"}</option>
            <option value="rellabels">{showRelLabels ? "✓ edge labels" : "edge labels"}</option>
          </select>
        </div>
        <div className="kg-canvas-wrap" ref={wrapRef}>
          <canvas ref={setCanvasEl} className="kg-canvas" />
          {data && data.nodes.length === 0 && (
            <div className="kg-empty">no graph yet — ingested papers and their concepts appear here</div>
          )}
          {tip && (
            <div
              className="kg-tooltip"
              style={{ left: Math.min(tip.sx + 14, (wrapRef.current?.clientWidth ?? 600) - 320), top: Math.max(4, tip.sy - 10) }}
            >
              <strong>{tip.d.label}</strong>
              <span className="pill kind">{tip.d.type}</span>
              {tip.d.seed && <span className="pill">match</span>}
              {(() => {
                const sci = scientistRef.current?.byId[tip.d.id.split("v")[0]];
                if (!sci) return null;
                const tldrKey = `sci-${tip.d.id}`;
                if (!tldrCacheRef.current.has(tldrKey)) {
                  tldrCacheRef.current.set(tldrKey, "…");
                  api
                    .postTldr({ text: `${sci.title}. ${sci.section}`, focus: sci.title })
                    .then((r) => {
                      tldrCacheRef.current.set(tldrKey, r.tldr);
                      forceTick((n) => n + 1);
                    })
                    .catch(() => tldrCacheRef.current.delete(tldrKey));
                }
                return (
                  <>
                    <span className="pill" style={{ borderColor: SCIENTIST_COLOR, color: SCIENTIST_COLOR }}>AI-Scientist</span>
                    <p style={{ margin: "4px 0 0", fontSize: 11 }}>
                      TLDR: {tldrCacheRef.current.get(tldrKey)}
                    </p>
                    {sci.section && (
                      <p style={{ margin: "4px 0 0", fontSize: 11 }}>
                        {sci.section}
                        {sci.year ? ` · ${sci.year}.${sci.month}` : ""}
                      </p>
                    )}
                    <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                      {sci.url && <a href={sci.url} target="_blank" rel="noreferrer">paper ↗</a>}
                      {sci.review_url && <a href={sci.review_url} target="_blank" rel="noreferrer">review ↗</a>}
                    </div>
                  </>
                );
              })()}
              {tip.d.definition && <p>{tip.d.definition}</p>}
              {tip.relations.length > 0 && (
                <ul className="kg-tip-rels">
                  {tip.relations.slice(0, 6).map((r, i) => (
                    <li key={i}>
                      <span style={{ color: relStyle(r.rel).color }}>{r.rel}</span> {r.dir} {r.other.label.slice(0, 30)}
                    </li>
                  ))}
                  {tip.relations.length > 6 && <li>+{tip.relations.length - 6} more</li>}
                </ul>
              )}
              {tip.pinned && <span className="stat">pinned — click node again to unpin</span>}
            </div>
          )}
          <div className="kg-legend">
            <span><i style={{ background: PAPER_COLOR }} /> papers</span>
            <span><i style={{ background: CONCEPT_COLOR }} /> concepts</span>
            <span><i style={{ background: LINEAGE_COLOR }} /> cited</span>
            <span><i style={{ background: SCIENTIST_COLOR }} /> AI-Scientist</span>
            <span><i style={{ background: REL_COLORS.cites.color }} /> cites</span>
            <span><i style={{ background: REL_COLORS.extends.color }} /> extends</span>
            <span><i style={{ background: REL_COLORS.related_to.color }} /> related</span>
            <span className="stat" style={{ marginLeft: 6, opacity: 0.8 }}>kg v5 · fluid</span>
          </div>
        </div>
      </div>
    </div>
  );
}
