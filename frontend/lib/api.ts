// Typed fetch wrappers for the 10 backend endpoints.

import type {
  CitationRef,
  FileSlice,
  Repo,
  Session,
  SessionMessage,
  ToolEvent,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── plain JSON endpoints ──────────────────────────────────────────────
export async function listRepos(): Promise<Repo[]> {
  const r = await fetch(`${API}/repos`);
  if (!r.ok) throw new Error(`GET /repos: ${r.status}`);
  return r.json();
}

export async function repoStatus(name: string): Promise<Repo> {
  const r = await fetch(`${API}/repos/${encodeURIComponent(name)}/status`);
  if (!r.ok) throw new Error(`GET /repos/${name}/status: ${r.status}`);
  return r.json();
}

export async function triggerIndex(name: string): Promise<{ job_id: string; status: string }> {
  const r = await fetch(`${API}/repos/${encodeURIComponent(name)}/index`, { method: "POST" });
  if (!r.ok) throw new Error(`POST /repos/${name}/index: ${r.status}`);
  return r.json();
}

export async function listSessions(): Promise<Session[]> {
  const r = await fetch(`${API}/sessions`);
  if (!r.ok) throw new Error(`GET /sessions: ${r.status}`);
  return r.json();
}

export async function sessionMessages(id: string): Promise<SessionMessage[]> {
  const r = await fetch(`${API}/sessions/${encodeURIComponent(id)}/messages`);
  if (!r.ok) throw new Error(`GET /sessions/${id}/messages: ${r.status}`);
  return r.json();
}

export async function deleteSession(id: string): Promise<void> {
  const r = await fetch(`${API}/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE /sessions/${id}: ${r.status}`);
}

export async function readFile(
  path: string, start = 1, end = 0, repo?: string,
): Promise<FileSlice> {
  const params = new URLSearchParams({ path, start: String(start), end: String(end) });
  if (repo) params.set("repo", repo);
  const r = await fetch(`${API}/files?${params}`);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || `GET /files: ${r.status}`);
  }
  return r.json();
}

// ── streaming /chat endpoint ──────────────────────────────────────────
export interface ChatStreamHandlers {
  onToolStart: (e: ToolEvent) => void;
  onToolEnd:   (e: ToolEvent) => void;
  onToken:     (text: string) => void;
  onCitations: (refs: CitationRef[]) => void;
  onError?:    (msg: string) => void;
  onDone?:     () => void;
}

export async function streamChat(
  body: { session_id: string; repo: string; message: string },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!r.ok) {
    const text = await r.text().catch(() => "");
    handlers.onError?.(text || `POST /chat: ${r.status}`);
    return;
  }
  if (!r.body) {
    handlers.onError?.("response has no body");
    return;
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line ("\n\n").
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      _dispatch(frame, handlers);
    }
  }
  // Flush any trailing frame
  if (buffer.trim()) _dispatch(buffer, handlers);
}

function _dispatch(frame: string, h: ChatStreamHandlers): void {
  let event = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  if (!event) return;

  let payload: any;
  try {
    payload = JSON.parse(data);
  } catch {
    return;
  }

  switch (event) {
    case "tool_start": h.onToolStart(payload); break;
    case "tool_end":   h.onToolEnd(payload); break;
    case "token":      if (payload.text) h.onToken(payload.text); break;
    case "citations":  h.onCitations(payload.refs || []); break;
    case "error":      h.onError?.(payload.message || "stream error"); break;
    case "done":       h.onDone?.(); break;
  }
}
