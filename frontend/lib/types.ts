// Shared types — mirror the backend Pydantic models.

export interface Repo {
  name: string;
  indexed: boolean;
  chunk_count: number;
  last_indexed_at: string | null;
  state: "ready" | "indexing" | "not_indexed" | "error";
  progress: number;
}

export interface Session {
  id: string;
  title: string;
  repo: string;
  created_at: string;
  last_message_at: string;
  message_count: number;
}

export interface SessionMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  name?: string | null;
  tool_calls?: { name: string; args: Record<string, unknown> }[] | null;
}

export interface FileSlice {
  path: string;
  start: number;
  end: number;
  total_lines: number;
  language: string;
  content: string;
}

export interface CitationRef {
  id: number;
  path: string;
  start: number;
  end: number;
  kind: string;
  symbol: string;
}

export interface ToolEvent {
  tool: string;
  args?: Record<string, unknown>;
  hits?: number;
  preview?: string;
}

// Frontend-internal — assembled message in the current chat
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: CitationRef[];
  toolEvents?: ToolEvent[];
}
