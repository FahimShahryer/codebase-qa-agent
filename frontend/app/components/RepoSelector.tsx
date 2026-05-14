"use client";

import { useEffect, useState } from "react";

import { listRepos } from "@/lib/api";
import type { Repo } from "@/lib/types";

interface Props {
  value: string;
  onChange: (repo: string) => void;
}

export default function RepoSelector({ value, onChange }: Props) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRepos()
      .then((rs) => {
        setRepos(rs);
        // Default-select the first repo if none chosen yet
        if (!value && rs.length > 0) onChange(rs[0].name);
      })
      .catch((e) => setError(String(e.message || e)));
  }, [value, onChange]);

  if (error) {
    return <span style={{ color: "#cf222e", fontSize: "0.85rem" }}>repos: {error}</span>;
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <label style={{ fontSize: "0.85rem", color: "#57606a" }}>Repo:</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: "0.3rem 0.5rem",
          borderRadius: 4,
          border: "1px solid #d0d7de",
          background: "#fff",
          fontFamily: "monospace",
          fontSize: "0.85rem",
        }}
      >
        {repos.length === 0 && <option value="">no indexed repos</option>}
        {repos.map((r) => (
          <option key={r.name} value={r.name}>
            {r.name} · {r.chunk_count} chunks · {r.state}
          </option>
        ))}
      </select>
    </div>
  );
}
