"use client";

import { useEffect, useRef, useState } from "react";

function useSeed(seed: string | null | undefined, consume: (() => void) | undefined,
                 send: (text: string) => void) {
  const sent = useRef<string | null>(null);
  useEffect(() => {
    if (seed && sent.current !== seed) {
      sent.current = seed;
      send(seed);
      consume?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);
}

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolsUsed?: string[];
  timestamps?: string[];
  model?: string;
  warnings?: string[];
}

const SUGGESTED = [
  "Why didn't it trade today?",
  "How much did I pay in fees today?",
  "What is the current BTCUSDT signal?",
  "Explain slippage in simple language",
];

export function ChatPanel({ seed, onSeedConsumed }: {
  seed?: string | null; onSeedConsumed?: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [mode, setMode] = useState<"simple" | "technical">("simple");
  const bottom = useRef<HTMLDivElement>(null);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch(`${BASE}/api/v1/ai/chat`, {
        method: "POST",
        headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: conversationId,
                               explanation_mode: mode }),
      });
      if (res.status === 503) { setUnavailable(true); return; }
      const data = await res.json();
      setConversationId(data.conversation_id);
      setMessages((m) => [...m, {
        role: "assistant", content: data.message, toolsUsed: data.tools_used,
        timestamps: data.data_timestamps, model: data.model, warnings: data.warnings,
      }]);
    } catch {
      setMessages((m) => [...m, { role: "assistant",
        content: "The assistant is unreachable. Trading and reports continue normally without it." }]);
    } finally {
      setBusy(false);
      bottom.current?.scrollIntoView({ behavior: "smooth" });
    }
  };

  const clear = async () => {
    if (conversationId) {
      await fetch(`${BASE}/api/v1/ai/clear`, {
        method: "POST",
        headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId }),
      }).catch(() => {});
    }
    setMessages([]);
    setConversationId(null);
  };

  useSeed(seed, onSeedConsumed, send);   // contextual "ask AI" seeds from other panels

  if (unavailable) {
    return <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
      AI assistant is not configured (set ANTHROPIC_API_KEY in .env and restart the API).
      Everything else works without it.</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: 460 }}>
      <div style={{ flex: 1, overflowY: "auto", paddingRight: 4 }}>
        {messages.length === 0 && (
          <div>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 8 }}>
              Ask about your portfolio, signals, fees, or how the app works.
            </p>
            {SUGGESTED.map((s) => (
              <button key={s} onClick={() => send(s)}
                style={{ display: "block", margin: "4px 0", fontSize: 12 }}>{s}</button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ margin: "8px 0" }}>
            <div style={{
              background: m.role === "user" ? "var(--surface-2)" : "transparent",
              border: m.role === "assistant" ? "1px solid var(--border)" : "none",
              borderRadius: 10, padding: "8px 12px", fontSize: 13,
              whiteSpace: "pre-wrap", lineHeight: 1.5,
            }}>
              {m.content}
            </div>
            {m.role === "assistant" && (m.toolsUsed?.length || m.warnings?.length) ? (
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, paddingLeft: 4 }}>
                {m.toolsUsed?.length ? `used: ${m.toolsUsed.join(", ")}` : ""}
                {m.timestamps?.length ? ` · data as of ${new Date(m.timestamps[0]).toLocaleTimeString()}` : ""}
                {m.warnings?.map((w, j) => <span key={j} style={{ color: "var(--amber)" }}> · {w}</span>)}
              </div>
            ) : null}
          </div>
        ))}
        {busy && <p style={{ color: "var(--text-muted)", fontSize: 12 }}>thinking…</p>}
        <div ref={bottom} />
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
          placeholder="Ask about your trading…"
          style={{ flex: 1 }} />
        <button className="primary" onClick={() => send(input)} disabled={busy}>Send</button>
        <button className="chip" title="Toggle explanation depth"
          onClick={() => setMode(mode === "simple" ? "technical" : "simple")}>
          {mode}
        </button>
        <button onClick={clear} title="Clear chat" aria-label="Clear chat">🗑</button>
      </div>
      <p style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
        AI answers may be imperfect; verify before acting. No profit is guaranteed.
      </p>
    </div>
  );
}
