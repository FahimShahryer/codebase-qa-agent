"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { renderCitations } from "./CitationBadge";
import ThinkingTrace from "./ThinkingTrace";
import type { ChatMessage, CitationRef } from "@/lib/types";

interface Props {
  message: ChatMessage;
  onCitationClick: (ref: CitationRef) => void;
}

export default function MessageView({ message, onCitationClick }: Props) {
  const isUser = message.role === "user";

  return (
    <div
      style={{
        margin: "1rem 0",
        padding: "0.75rem 1rem",
        background: isUser ? "#dbeafe" : "#fff",
        border: isUser ? "1px solid #93c5fd" : "1px solid #d0d7de",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          fontSize: "0.72rem",
          fontWeight: 600,
          color: isUser ? "#1e40af" : "#0d9488",
          marginBottom: 4,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {isUser ? "You" : "Assistant"}
      </div>

      {/* Tool calls timeline for assistant messages */}
      {!isUser && message.toolEvents && message.toolEvents.length > 0 && (
        <ThinkingTrace items={message.toolEvents as any} />
      )}

      {/* Markdown body with citation badge substitution */}
      <div style={{ fontSize: "0.95rem", lineHeight: 1.55 }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // For plain text, run citation replacement
            p: ({ children, ...props }) => (
              <p {...props}>{wrapKids(children, message.citations || [], onCitationClick)}</p>
            ),
            li: ({ children, ...props }) => (
              <li {...props}>{wrapKids(children, message.citations || [], onCitationClick)}</li>
            ),
            code: ({ children, ...props }: any) => (
              <code
                {...props}
                style={{
                  background: "#f6f8fa",
                  padding: "1px 4px",
                  borderRadius: 3,
                  fontFamily: "monospace",
                  fontSize: "0.85em",
                }}
              >
                {children}
              </code>
            ),
            pre: ({ children, ...props }) => (
              <pre
                {...props}
                style={{
                  background: "#f6f8fa",
                  padding: "0.75rem",
                  borderRadius: 6,
                  overflow: "auto",
                  fontSize: "0.82rem",
                }}
              >
                {children}
              </pre>
            ),
          }}
        >
          {message.content || (isUser ? "" : "…")}
        </ReactMarkdown>
      </div>
    </div>
  );
}

// Walk react children, replacing citation markers within text nodes.
function wrapKids(
  children: React.ReactNode,
  refs: CitationRef[],
  onClick: (r: CitationRef) => void,
): React.ReactNode {
  if (typeof children === "string") {
    return renderCitations(children, refs, onClick);
  }
  if (Array.isArray(children)) {
    return children.map((c, i) =>
      typeof c === "string"
        ? <span key={i}>{renderCitations(c, refs, onClick)}</span>
        : c,
    );
  }
  return children;
}
