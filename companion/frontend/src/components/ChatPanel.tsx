import { useCallback, useEffect, useRef, useState } from "react";
import { api, req } from "../api";
import { marked } from "marked";
import { toast } from "../lib/toast";
import type { ChatMessage } from "../types";

marked.setOptions({ breaks: true, gfm: true });

const FOX_MODES = ["fast", "rag", "thinking", "deep-thinking", "deep-research"];
const CHAT_STORAGE_KEY = "fox-chat-v1";

const FOX_SAMPLES: { label: string; prompt: string; mode?: string }[] = [
  { label: "Summarize my library", prompt: "Summarize the key trends across my ingested papers", mode: "rag" },
  { label: "What’s new?", prompt: "What’s new this week? Give me a digest of recent papers", mode: "rag" },
  { label: "Compare papers", prompt: "Compare the two most recent papers on federated learning", mode: "deep-thinking" },
  { label: "Deep research", prompt: "What are the open problems in vision-language models?", mode: "deep-research" },
  { label: "Survey", prompt: "Survey recent work on AI agents and LLM adoption in enterprises", mode: "deep-research" },
  { label: "Explain GNNs", prompt: "Explain graph neural networks like I’m 5", mode: "fast" },
];

interface PersistedChat {
  messages: ChatMessage[];
  conversationId: string | null;
  mode: string;
}

function loadPersisted(): PersistedChat {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as PersistedChat;
      if (Array.isArray(parsed.messages)) return parsed;
    }
  } catch {
    /* corrupt or unavailable storage */
  }
  return { messages: [], conversationId: null, mode: "rag" };
}

export function ChatPanel() {
  const initial = loadPersisted();
  const [messages, setMessages] = useState<ChatMessage[]>(initial.messages.slice(-50));
  const [input, setInput] = useState("");
  const [mode, setMode] = useState(initial.mode);
  const [conversationId, setConversationId] = useState<string | null>(initial.conversationId);
  const [busy, setBusy] = useState(false);
  const [modes, setModes] = useState<string[]>(FOX_MODES);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // hive may expose different fox modes; fall back to the known list.
    // quiet: older hive builds 404 here — not worth the global error banner.
    req<{ modes?: unknown[] }>("/api/fox/modes", { quiet: true })
      .then((d) => {
        const list = (d.modes ?? [])
          .map((m) => (typeof m === "string" ? m : typeof m === "object" && m !== null && "name" in m ? String((m as { name: unknown }).name) : ""))
          .filter(Boolean);
        if (list.length) setModes(list);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(
        CHAT_STORAGE_KEY,
        JSON.stringify({ messages: messages.slice(-50), conversationId, mode } satisfies PersistedChat),
      );
    } catch {
      /* storage full or unavailable */
    }
  }, [messages, conversationId, mode]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const onPrefill = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (text) {
        setInput(text);
        window.dispatchEvent(new CustomEvent("fox-focus-chat"));
      }
    };
    window.addEventListener("fox-prefill", onPrefill);
    return () => window.removeEventListener("fox-prefill", onPrefill);
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const reply = await api.chat(text, mode, conversationId);
      if (reply.conversation_id) setConversationId(reply.conversation_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: reply.answer,
          sources: reply.sources,
          grounded: reply.grounded,
          memoryRecalled: reply.memory_recalled,
        },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: `Error: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    } finally {
      setBusy(false);
    }
  }, [input, busy, mode, conversationId]);

  return (
    <div className="chat">
      <div className="chat-head">
        <h2>
          <img src="/fox-avatar.webp" alt="" className="chat-fox-icon" width={22} height={22} onError={(e) => ((e.currentTarget.style.display = "none"))} />
          Fox Chat
        </h2>
        <select value={mode} onChange={(e) => setMode(e.target.value)} title="Fox reasoning mode">
          {modes.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      <div className="chat-log">
        {messages.length === 0 && (
          <div className="chat-empty">
            <img src="/fox-avatar.webp" alt="Fox" className="chat-empty-fox" width={72} height={72} onError={(e) => ((e.currentTarget.style.display = "none"))} />
            <p className="empty">Ask anything about your library. Answers are grounded in your notes and knowledge graph; every exchange becomes an episode the companion can recall.</p>
            <div className="sample-commands" aria-label="sample prompts">
              <span className="artifact-label" style={{ display: "block", marginTop: 10, marginBottom: 6 }}>
                Try a sample:
              </span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center" }}>
                {FOX_SAMPLES.map((s) => (
                  <button
                    key={s.label}
                    className="chip"
                    title={`${s.mode ? `mode: ${s.mode} — ` : ""}${s.prompt}`}
                    onClick={() => {
                      setInput(s.prompt);
                      if (s.mode && FOX_MODES.includes(s.mode)) setMode(s.mode);
                      // focus the textarea next tick
                      setTimeout(() => {
                        const ta = document.querySelector<HTMLTextAreaElement>(".chat-input textarea");
                        ta?.focus();
                      }, 0);
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            {m.role === "assistant" && <img src="/fox-avatar.webp" alt="" className="msg-fox" width={18} height={18} onError={(e) => ((e.currentTarget.style.display = "none"))} />}
            <div className="msg-body">
              {m.role === "assistant" ? (
                <div className="msg-text msg-md" dangerouslySetInnerHTML={{ __html: marked.parse(m.text) as string }} />
              ) : (
                <p className="msg-text">{m.text}</p>
              )}
              {m.memoryRecalled && m.memoryRecalled.length > 0 && (
                <details className="memory">
                  <summary>recalled {m.memoryRecalled.length} episodes</summary>
                  <ul>
                    {m.memoryRecalled.map((e, j) => (
                      <li key={j}>
                        [{e.kind}] {e.summary}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {m.sources && m.sources.length > 0 && (
                <details className="sources">
                  <summary>{m.sources.length} sources</summary>
                  <ul>
                    {m.sources.map((s, j) => (
                      <li key={j}>{s.title || s.paper_id}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </div>
        ))}
        {busy && <p className="typing">the fox is thinking…</p>}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Ask the fox…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button
          className="ghost"
          title="clear conversation"
          onClick={() => {
            setMessages([]);
            setConversationId(null);
            toast("conversation cleared", "info");
          }}
        >
          ⌫ clear
        </button>
        <button onClick={() => void send()} disabled={busy}>
          send
        </button>
      </div>
    </div>
  );
}
