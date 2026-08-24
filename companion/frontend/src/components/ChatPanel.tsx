import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatMessage } from "../types";

const FOX_MODES = ["fast", "rag", "thinking", "deep-thinking", "deep-research"];

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState("rag");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
        <h2>Companion Chat</h2>
        <select value={mode} onChange={(e) => setMode(e.target.value)} title="Fox reasoning mode">
          {FOX_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      <div className="chat-log">
        {messages.length === 0 && (
          <p className="empty">Ask anything about your library. Answers are grounded in your notes and knowledge graph; every exchange becomes an episode the companion can recall.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            <p className="msg-text">{m.text}</p>
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
        ))}
        {busy && <p className="typing">companion is thinking…</p>}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Ask the companion…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button onClick={() => void send()} disabled={busy}>
          send
        </button>
      </div>
    </div>
  );
}
