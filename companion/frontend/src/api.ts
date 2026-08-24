import type { Approval, AppState, AutonomyMode, Episode, Plan, Suggestion, TimelineResponse } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body.slice(0, 200)}`);
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
};

export function connectWs(onEvent: (event: MessageEvent) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
  ws.onmessage = onEvent;
  return ws;
}
