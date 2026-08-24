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
}

export interface ArtifactGroup {
  id: string;
  label: string;
  files: ArtifactFile[];
  total: number;
}
