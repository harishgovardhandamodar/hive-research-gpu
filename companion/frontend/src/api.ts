import type {
  Approval,
  AppState,
  ArtifactGroup,
  ArtifactNode,
  AutonomyMode,
  Episode,
  Plan,
  Suggestion,
  TimelineResponse,
  RelatedSubgraph,
  KGData,
  PoolPaper,
  LibraryHit,
  Schedule,
   CompareEdge,
   IngestFailure,
   PlanTemplate,
   ScientistPayload,
 } from "./types";

export async function req<T>(path: string, init?: RequestInit & { quiet?: boolean }): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.text();
    const message = `${resp.status}: ${body.slice(0, 200)}`;
    // surface failures globally unless the caller opts out (best-effort calls)
    if (!init?.quiet) {
      window.dispatchEvent(new CustomEvent("api-error", { detail: { path, message } }));
    }
    throw new Error(message);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  state: () => req<AppState>("/api/state"),
  tools: () => req<{ name: string; mutates: boolean }[]>("/api/tools"),
  createGoal: (goal: string, mode: AutonomyMode) =>
    req<Plan>("/api/goals", { method: "POST", body: JSON.stringify({ goal, mode }) }),
  plans: () => req<Plan[]>("/api/plans"),
  plan: (id: string) => req<Plan>(`/api/plans/${id}`),
  switchMode: (planId: string, mode: AutonomyMode) =>
    req<{ plan_id: string; mode: string }>(`/api/plans/${planId}/mode`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  pendingApprovals: () => req<Approval[]>("/api/approvals"),
  decideApproval: (id: string, approved: boolean, note = "") =>
    req<Approval>(`/api/approvals/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ approved, note }),
    }),
  suggestions: () => req<Suggestion[]>("/api/suggestions"),
  acceptSuggestion: (id: string, mode: AutonomyMode) =>
    req<Plan>(`/api/suggestions/${id}/accept`, { method: "POST", body: JSON.stringify({ mode }) }),
  rejectSuggestion: (id: string) =>
    req<Suggestion>(`/api/suggestions/${id}/reject`, { method: "POST", body: "{}" }),
  episodes: (query = "", limit = 60) =>
    req<{ items: Episode[] }>(`/api/episodes?query=${encodeURIComponent(query)}&limit=${limit}`),
  timeline: () => req<TimelineResponse>("/api/timeline?limit=40"),
  artifacts: () => req<{ groups: ArtifactGroup[] }>("/api/artifacts"),
  explorer: () => req<ArtifactNode>("/api/explorer"),
  kg: () => req<KGData>("/api/kg"),
  kgSearch: (q: string) =>
    req<KGData>(`/api/kg/search?q=${encodeURIComponent(q)}`),
  discover: () =>
    req<{ topics: string[]; papers: PoolPaper[] }>("/api/discover"),
  importPoolPaper: (arxivId: string, mode: string) =>
    req<Plan>("/api/discover/import", {
      method: "POST",
      body: JSON.stringify({ arxiv_id: arxivId, mode }),
    }),
  ingestFailures: () =>
    req<{ count: number; failures: IngestFailure[] }>("/api/ingest/failures"),
  retryIngest: (arxivIds: string[], mode = "tiered") =>
    req<Plan>("/api/ingest/retry", {
      method: "POST",
      body: JSON.stringify({ arxiv_ids: arxivIds, mode }),
    }),
  dismissIngestFailure: (arxivId: string) =>
    req<{ dismissed: string }>(`/api/ingest/failures/${encodeURIComponent(arxivId)}`, {
      method: "DELETE",
    }),
  poolTopic: (action: "add" | "remove", topic: string) =>
    req<unknown>("/api/discover/topics", {
      method: "POST",
      body: JSON.stringify({ action, topic }),
    }),
  librarySearch: (q: string) =>
    req<{ items: LibraryHit[] }>(`/api/library/search?q=${encodeURIComponent(q)}`),
  rateArtifact: (kind: string, rating: number, comment = "") =>
    req<unknown>("/api/rate", {
      method: "POST",
      body: JSON.stringify({ kind, rating, comment }),
    }),
  schedules: () => req<Schedule[]>("/api/schedules"),
  addSchedule: (goal: string, mode: string, cadence: string, weekday: number) =>
    req<Schedule>("/api/schedules", {
      method: "POST",
      body: JSON.stringify({ goal, mode, cadence, weekday }),
    }),
  deleteSchedule: (id: string) => req<{ deleted: string }>(`/api/schedules/${id}`, { method: "DELETE" }),
  toggleSchedule: (id: string) =>
    req<Schedule>(`/api/schedules/${id}/toggle`, { method: "POST", body: "{}" }),
  cite: (arxivId: string, title = "", authors = "", published = "") =>
    req<{ bibtex: string }>(
      `/api/cite?arxiv_id=${encodeURIComponent(arxivId)}&title=${encodeURIComponent(title)}&authors=${encodeURIComponent(authors)}&published=${encodeURIComponent(published)}`,
    ),
  similarity: (paperIds: string[]) =>
    req<CompareEdge[]>("/api/similarity", {
      method: "POST",
      body: JSON.stringify({ paper_ids: paperIds }),
    }),
  artifactRelated: (path: string) =>
    req<RelatedSubgraph>(`/api/artifacts/related?path=${encodeURIComponent(path)}`),
  artifactContent: (path: string) =>
    req<{ path: string; content: string }>(`/api/artifacts/content?path=${encodeURIComponent(path)}`),
  chat: (message: string, mode: string, conversationId?: string | null) =>
    req<{
      answer: string;
      sources?: { title?: string; paper_id?: string }[];
      grounded?: boolean;
      conversation_id?: string;
      memory_recalled?: { kind: string; ts: string; summary: string }[];
    }>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, mode, conversation_id: conversationId ?? undefined }),
    }),
  runProactive: () => req<{ created: Suggestion[] }>("/api/proactive/run", { method: "POST", body: "{}" }),
  planTemplates: () => req<PlanTemplate[]>("/api/plans/templates"),
  scientistExcerpts: () => req<ScientistPayload>("/api/scientist", { quiet: true }),
  scientistRefresh: () => req<Record<string, unknown>>("/api/scientist/refresh", { method: "POST", body: "{}" }),
  scientistImport: (arxivId: string, mode = "tiered") =>
    req<Plan>("/api/scientist/import", {
      method: "POST",
      body: JSON.stringify({ arxiv_id: arxivId, mode }),
    }),
  runPlanTemplate: (id: string, mode = "tiered") =>
    req<Plan>(`/api/plans/templates/${id}/run`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  deletePlanTemplate: (id: string) =>
    req<{ deleted: string }>(`/api/plans/templates/${id}`, { method: "DELETE" }),
};

export function connectWs(onEvent: (event: MessageEvent) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
  ws.onmessage = onEvent;
  return ws;
}
