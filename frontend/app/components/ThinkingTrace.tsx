"use client";

import type { ToolEvent } from "@/lib/types";

type Item =
  | { kind: "start"; tool: string; args?: Record<string, unknown> }
  | { kind: "end";   tool: string; hits?: number; preview?: string };

const TOOL_ICON: Record<string, string> = {
  search_code: "🔍",
  read_file: "📄",
  list_directory: "📁",
  summarize_module: "📝",
  find_callers: "🔁",
  find_importers: "📥",
  find_definition: "🎯",
};

export default function ThinkingTrace({ items }: { items: Item[] }) {
  if (items.length === 0) return null;

  return (
    <div
      style={{
        borderLeft: "2px solid #d0d7de",
        paddingLeft: "0.75rem",
        margin: "0.5rem 0 0.75rem 0",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: "0.8rem",
        color: "#57606a",
      }}
    >
      {items.map((it, idx) => {
        const icon = TOOL_ICON[it.tool] ?? "🔧";
        if (it.kind === "start") {
          const args = it.args ? formatArgs(it.args) : "";
          return (
            <div key={idx} style={{ padding: "2px 0" }}>
              {icon} <strong>{it.tool}</strong>
              {args && <span style={{ color: "#8c959f" }}>({args})</span>}
            </div>
          );
        }
        return (
          <div key={idx} style={{ padding: "2px 0 6px 1.25rem", color: "#8c959f" }}>
            ← {it.hits !== undefined ? `${it.hits} hits` : ""}
            {it.preview ? ` · ${truncate(it.preview, 100)}` : ""}
          </div>
        );
      })}
    </div>
  );
}

function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
