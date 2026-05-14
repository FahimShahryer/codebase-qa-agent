"use client";

import { useEffect, useState } from "react";

import { deleteSession, listSessions } from "@/lib/api";
import type { Session } from "@/lib/types";

interface Props {
  currentSessionId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  reloadKey?: number;       // bump to force a refetch
}

export default function SessionSidebar({
  currentSessionId, onSelect, onNew, reloadKey,
}: Props) {
  const [sessions, setSessions] = useState<Session[]>([]);

  useEffect(() => {
    listSessions().then(setSessions).catch(() => setSessions([]));
  }, [reloadKey]);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteSession(id);
      setSessions((s) => s.filter((x) => x.id !== id));
      if (id === currentSessionId) onNew();
    } catch (err) {
      // ignore — show in console only
      console.error(err);
    }
  };

  return (
    <aside
      style={{
        width: 260,
        borderRight: "1px solid #d0d7de",
        padding: "1rem 0.75rem",
        background: "#f6f8fa",
        height: "100vh",
        boxSizing: "border-box",
        overflow: "auto",
      }}
    >
      <button
        onClick={onNew}
        style={{
          width: "100%",
          padding: "0.5rem",
          marginBottom: "0.75rem",
          border: "1px solid #d0d7de",
          borderRadius: 6,
          background: "#fff",
          cursor: "pointer",
          fontSize: "0.9rem",
        }}
      >
        + New chat
      </button>

      <div style={{ fontSize: "0.78rem", color: "#57606a", margin: "0.5rem 0 0.25rem" }}>
        {sessions.length === 0 ? "No sessions yet" : `${sessions.length} sessions`}
      </div>

      {sessions.map((s) => {
        const active = s.id === currentSessionId;
        return (
          <div
            key={s.id}
            onClick={() => onSelect(s.id)}
            style={{
              padding: "0.5rem",
              marginBottom: 4,
              borderRadius: 4,
              cursor: "pointer",
              background: active ? "#dbeafe" : "transparent",
              border: active ? "1px solid #0969da" : "1px solid transparent",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: "0.85rem",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {s.title}
              </div>
              <div style={{ fontSize: "0.72rem", color: "#57606a" }}>
                {s.repo} · {s.message_count} msg
              </div>
            </div>
            <button
              onClick={(e) => handleDelete(e, s.id)}
              style={{
                border: 0, background: "transparent",
                color: "#8c959f", cursor: "pointer", padding: "0 4px",
                fontSize: "1rem", lineHeight: 1,
              }}
              aria-label="Delete session"
              title="Delete session"
            >×</button>
          </div>
        );
      })}
    </aside>
  );
}
