export interface Step {
  index: number;
  tool: string;
  args: Record<string, unknown>;
  rationale: string;
  state: "pending" | "awaiting_approval" | "running" | "done" | "skipped" | "failed";
}

export interface Plan {
  id: string;
  goal_id: string;
  goal: string;
  steps: Step[];
  planner: string;
  status: string;
}

export type AutonomyMode = "approve" | "tiered" | "auto";

export interface Suggestion {
  id: string;
  kind: string;
  title: string;
  rationale: string;
  tool: string;
  args: Record<string, unknown>;
  score: number;
  signal?: string;
  created?: string;
}

export interface Approval {
  id: string;
  plan_id: string;
  step_index: number;
  tool: string;
  args: Record<string, unknown>;
  rationale: string;
  created: string;
}

export interface Episode {
  id: string;
  ts: string;
  kind: string;
  summary: string;
  session_id: string;
  goal_id: string;
  context: Record<string, unknown>;
}

export interface AppState {
  session_id: string;
  hive_url: string;
  hive_ok: boolean;
  hive_stats: Record<string, unknown>;
  llm_available: boolean;
  llm_model: string | null;
  autonomy_modes: string[];
  proactive: { at: string | null; signals: Record<string, number>; new: number };
  episodes: { count: number; by_kind: Record<string, number> };
  policy: { weights: Record<string, number>; window: number };
  ws_clients: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  mode?: string;
  sources?: { title?: string; paper_id?: string }[];
  memoryRecalled?: { kind: string; ts: string; summary: string }[];
  grounded?: boolean;
}

export interface TimelineStep {
  ts: string;
  tool: string;
  status: string;
  summary: string;
}

export interface TimelineThread {
  goal_id: string;
  goal: string;
  started: string;
  last: string;
  span_s: number;
  status: string;
  steps_ok: number;
  steps_failed: number;
  steps_skipped: number;
  steps: TimelineStep[];
  decisions: { ts: string; summary: string }[];
}

export interface TimelineResponse {
  threads: TimelineThread[];
  unfiled: { ts: string; kind: string; summary: string }[];
  total_threads: number;
}

export interface ArtifactFile {
  name: string;
  path: string;
  mtime?: number;
}

export interface ArtifactGroup {
  id: string;
  label: string;
  files: ArtifactFile[];
  total: number;
}

export interface ArtifactNode {
  name: string;
  type: "dir" | "file";
  path?: string;
  ext?: string;
  mtime?: number;
  view?: "text" | "image" | "none";
  children?: ArtifactNode[];
}

export interface KGNode {
  id: string;
  label: string;
  type: string;
  seed?: boolean;
  definition?: string;
}

export interface KGData {
  nodes: KGNode[];
  links: { source: string; target: string; relation: string }[];
}

export interface RelatedSubgraph {
  seeds: { id: string; label: string }[];
  papers: { id: string; label: string; score: number; direct: boolean }[];
  concepts: { id: string; label: string; links: number }[];
  keywords: string[];
}

export interface PoolPaper {
  arxiv_id: string;
  title: string;
  authors: string;
  published: string;
  abstract: string;
  topics: string[];
  imported: boolean;
}

export interface LibraryHit {
  arxiv_id: string;
  title: string;
  authors: string;
  published: string;
  abstract: string;
  note_path: string | null;
}

export interface Schedule {
  id: string;
  goal: string;
  mode: string;
  cadence: string;
  weekday: number;
  enabled: boolean;
  last_run: string | null;
}

export interface CompareEdge {
  source: string;
  source_title: string;
  target: string;
  target_title: string;
  score: number;
  author_overlap: number;
  abstract_sim: number;
}

export interface IdeaRunState {
  id: string;
  topic: string;
  status: "idle" | "running" | "done" | "failed" | "cancelled";
  error?: string | null;
  iterations: number;
  archive_cells: number;
  cells_filled: number;
  candidates_seen: number;
  ideas: {
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
  }[];
}
