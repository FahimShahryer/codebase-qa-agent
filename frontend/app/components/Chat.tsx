"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { sessionMessages, streamChat } from "@/lib/api";
import type { ChatMessage, CitationRef } from "@/lib/types";

import CitationPanel from "./CitationPanel";
import MessageView from "./Message";

interface Props {
  sessionId: string;
  repo: string;
  onSessionUsed: () => void;   // bump SessionSidebar after a successful turn
}

export default function Chat({ sessionId, repo, onSessionUsed }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<ChatMessage | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [panelRef, setPanelRef] = useState<CitationRef | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load prior conversation when session changes
  useEffect(() => {
    setMessages([]);
    setPending(null);
    setError(null);
    sessionMessages(sessionId)
      .then((rows) => {
        const collapsed: ChatMessage[] = [];
        for (const m of rows) {
          if (m.role === "user") {
            collapsed.push({ role: "user", content: m.content });
          } else if (m.role === "assistant" && m.content) {
            collapsed.push({ role: "assistant", content: m.content });
          }
          // tool rows are skipped on reload — they're transient signals,
          // not part of the user-facing conversation
        }
        setMessages(collapsed);
      })
      .catch(() => { /* fresh session is fine */ });
  }, [sessionId]);

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setPending({ role: "assistant", content: "", toolEvents: [], citations: [] });

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    let acc = "";

    try {
      await streamChat(
        { session_id: sessionId, repo, message: text },
        {
          onToolStart: (e) => {
            setPending((p) =>
              p ? { ...p, toolEvents: [...(p.toolEvents || []), { kind: "start", ...e }] } : p,
            );
          },
          onToolEnd: (e) => {
            setPending((p) =>
              p ? { ...p, toolEvents: [...(p.toolEvents || []), { kind: "end", ...e }] } : p,
            );
          },
          onToken: (t) => {
            acc += t;
            setPending((p) => (p ? { ...p, content: acc } : p));
          },
          onCitations: (refs) => {
            setPending((p) => (p ? { ...p, citations: refs } : p));
          },
          onError: (msg) => {
            setError(msg);
          },
          onDone: () => {},
        },
        ctrl.signal,
      );
    } catch (e: any) {
      setError(String(e.message || e));
    }

    // Commit the pending message into history
    setPending((p) => {
      if (p && p.content) {
        setMessages((m) => [...m, p]);
      }
      return null;
    });
    setBusy(false);
    abortRef.current = null;
    onSessionUsed();
  }, [input, busy, sessionId, repo, onSessionUsed]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <main
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        boxSizing: "border-box",
        background: "#fafafa",
      }}
    >
      {/* Scrollable conversation */}
      <div style={{ flex: 1, overflow: "auto", padding: "1rem 2rem" }}>
        {messages.length === 0 && !pending && (
          <div style={{ color: "#8c959f", padding: "1rem 0" }}>
            Ask anything about the indexed codebase. Try:
            <ul>
              <li>How does URL routing work?</li>
              <li>what calls make_response?</li>
              <li>Where is Blueprint defined?</li>
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageView key={i} message={m} onCitationClick={setPanelRef} />
        ))}
        {pending && (
          <MessageView message={pending} onCitationClick={setPanelRef} />
        )}
        {error && (
          <div style={{ padding: "0.75rem", color: "#cf222e", background: "#ffebe9", borderRadius: 6 }}>
            Error: {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div
        style={{
          borderTop: "1px solid #d0d7de",
          padding: "0.75rem 2rem",
          background: "#fff",
          display: "flex",
          gap: 8,
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={busy ? "Thinking…" : "Type a question, then Enter to send"}
          disabled={busy}
          rows={2}
          style={{
            flex: 1,
            padding: "0.5rem",
            borderRadius: 6,
            border: "1px solid #d0d7de",
            resize: "vertical",
            fontFamily: "inherit",
            fontSize: "0.95rem",
          }}
        />
        <button
          onClick={send}
          disabled={busy || !input.trim()}
          style={{
            padding: "0 1.25rem",
            background: busy ? "#94a3b8" : "#0969da",
            color: "#fff",
            border: 0,
            borderRadius: 6,
            cursor: busy ? "not-allowed" : "pointer",
            fontSize: "0.95rem",
          }}
        >
          Send
        </button>
      </div>

      {/* Citation panel (modal-style) */}
      <CitationPanel
        ref={panelRef}
        repo={repo}
        onClose={() => setPanelRef(null)}
      />
    </main>
  );
}
