"use client";

import { useEffect, useState } from "react";

import { readFile } from "@/lib/api";
import type { CitationRef, FileSlice } from "@/lib/types";

interface Props {
  ref: CitationRef | null;
  repo: string;
  onClose: () => void;
}

export default function CitationPanel({ ref, repo, onClose }: Props) {
  const [slice, setSlice] = useState<FileSlice | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ref) {
      setSlice(null);
      setError(null);
      return;
    }
    let cancelled = false;
    // Pull a bit of surrounding context for readability
    const padding = 5;
    const fetchStart = Math.max(1, ref.start - padding);
    const fetchEnd = ref.end + padding;
    readFile(ref.path, fetchStart, fetchEnd, repo)
      .then((s) => {
        if (!cancelled) {
          setSlice(s);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e.message || e));
      });
    return () => { cancelled = true; };
  }, [ref, repo]);

  if (!ref) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(15, 23, 42, 0.4)",
          zIndex: 10,
        }}
      />
      {/* Panel */}
      <aside
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(640px, 90vw)",
          background: "#fff",
          borderLeft: "1px solid #d0d7de",
          boxShadow: "-8px 0 24px rgba(0,0,0,0.12)",
          zIndex: 11,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          style={{
            padding: "0.75rem 1rem",
            borderBottom: "1px solid #d0d7de",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>
              {ref.kind}: {ref.symbol}
            </div>
            <div style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "#57606a" }}>
              {ref.path}:{ref.start}-{ref.end}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              border: 0, background: "transparent",
              fontSize: "1.4rem", cursor: "pointer", lineHeight: 1, color: "#57606a",
            }}
            aria-label="Close panel"
          >×</button>
        </header>
        <div style={{ flex: 1, overflow: "auto" }}>
          {error && (
            <div style={{ padding: "1rem", color: "#cf222e" }}>Error: {error}</div>
          )}
          {!error && !slice && (
            <div style={{ padding: "1rem", color: "#8c959f" }}>Loading…</div>
          )}
          {slice && (
            <pre
              style={{
                margin: 0,
                padding: "0.75rem 1rem",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: "0.82rem",
                lineHeight: 1.5,
                background: "#f6f8fa",
                color: "#1f2328",
                whiteSpace: "pre",
                overflow: "auto",
              }}
            >
              {slice.content.split("\n").map((line, i) => {
                const lineNum = slice.start + i;
                const inRange = lineNum >= ref.start && lineNum <= ref.end;
                return (
                  <div
                    key={i}
                    style={{
                      background: inRange ? "#fff8c5" : "transparent",
                      padding: "0 0.5rem",
                      marginLeft: "-0.5rem",
                      marginRight: "-0.5rem",
                    }}
                  >
                    <span style={{ display: "inline-block", width: "3rem", color: "#8c959f", userSelect: "none" }}>
                      {lineNum}
                    </span>
                    {line || " "}
                  </div>
                );
              })}
            </pre>
          )}
        </div>
      </aside>
    </>
  );
}
