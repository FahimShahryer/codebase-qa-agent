"use client";

import type { CitationRef } from "@/lib/types";

interface Props {
  refs: CitationRef[];
  onClick: (ref: CitationRef) => void;
}

/**
 * Renders inline `[path:start-end]` markers as clickable badges that map
 * back to the citations registry from the SSE `citations` event.
 *
 * Wraps a single string and returns spans + clickable buttons.
 */
export function renderCitations(
  text: string,
  refs: CitationRef[],
  onClick: (ref: CitationRef) => void,
): React.ReactNode {
  if (refs.length === 0) return text;

  // Build a path → ref index for lookup
  const byKey = new Map<string, CitationRef>();
  for (const r of refs) {
    byKey.set(`${r.path}:${r.start}-${r.end}`, r);
  }

  // Match `[path:start-end]` in the text
  const regex = /\[([^\]\s]+):(\d+)-(\d+)\]/g;
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;

  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      out.push(<span key={`t${key++}`}>{text.slice(last, m.index)}</span>);
    }
    const [, path, start, end] = m;
    const ref = byKey.get(`${path}:${start}-${end}`);
    if (ref) {
      out.push(
        <button
          key={`b${key++}`}
          onClick={(e) => { e.preventDefault(); onClick(ref); }}
          style={{
            display: "inline-block",
            padding: "0 6px",
            margin: "0 2px",
            border: "1px solid #d0d7de",
            borderRadius: 4,
            background: "#f6f8fa",
            color: "#0969da",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: "0.78rem",
            cursor: "pointer",
            verticalAlign: "baseline",
          }}
          title={`${ref.kind}: ${ref.symbol}`}
        >
          {path.split("/").pop()}:{start}-{end}
        </button>,
      );
    } else {
      // Unknown ref — render literal
      out.push(<span key={`u${key++}`}>{m[0]}</span>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<span key={`t${key++}`}>{text.slice(last)}</span>);
  return out;
}
